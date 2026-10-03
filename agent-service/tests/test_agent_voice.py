"""Isolated audio transport contracts; no real provider or microphone."""
import asyncio
import base64
import json
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agent_service import agent_voice as v
from agent_service.conversation_store import ConversationStore
from agent_service.harness_store import HarnessStore

PCM = base64.b64encode(b'\0' * 320).decode()


class FakeProvider:
    def __init__(self):
        self.events = asyncio.Queue()
        self.commands = asyncio.Queue()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return json.dumps(await self.events.get())

    async def send(self, raw):
        event = json.loads(raw)
        await self.commands.put(event)
        if event['type'] == 'session.update':
            await self.events.put({'type': 'session.updated'})

    async def command(self, kind):
        async def find():
            while True:
                event = await self.commands.get()
                if event['type'] == kind:
                    return event
        return await asyncio.wait_for(find(), 1)

    async def event(self, kind, **fields):
        await self.events.put(dict(type=kind, **fields))


class FakeClient:
    def __init__(self):
        self.input = asyncio.Queue()
        self.output = asyncio.Queue()

    async def receive_json(self):
        return await self.input.get()

    async def send_json(self, event):
        await self.output.put(event)

    async def send(self, kind, **fields):
        await self.input.put(dict(type=kind, **fields))

    async def receive(self):
        return await asyncio.wait_for(self.output.get(), 1)


class AgentVoiceContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConversationStore(HarnessStore(self.tmp.name + '/voice.sqlite3'))
        self.owner = str(uuid4())
        self.client, self.provider = FakeClient(), FakeProvider()
        self.bridge = v.AudioBridge(self.client, self.provider, v.OwnerFence(self.store, self.owner))
        self.running = asyncio.create_task(self.bridge.run())
        self.assertEqual((await self.client.receive())['type'], 'ready')

    async def asyncTearDown(self):
        self.running.cancel()
        await asyncio.gather(self.running, return_exceptions=True)
        self.tmp.cleanup()

    async def commit(self, generation=1):
        uid = str(uuid4())
        await self.client.send('audio', audio=PCM)
        await self.client.send('commit_audio', utterance_id=uid, generation=generation)
        await self.provider.command('input_audio_buffer.commit')
        return uid

    async def speak(self, text):
        sid = str(uuid4())
        await self.client.send('speak', text=text, speech_id=sid)
        await self.provider.command('response.create')
        return sid

    async def finish_response(self, rid, text):
        await self.provider.event('response.audio.delta', response_id=rid, delta=PCM)
        await self.provider.event('response.audio_transcript.delta', response_id=rid, delta=text)
        await self.provider.event('response.done', response={'id': rid, 'status': 'completed', 'usage': {'total_tokens': 3}})

    async def test_unknown_draft_becomes_active_without_audio_creating_session(self):
        self.assertIsNone(self.store.get(self.owner))
        uid = await self.commit(7)
        await self.provider.event('input_audio_buffer.committed', item_id='input1')
        await self.provider.event('conversation.item.input_audio_transcription.completed', item_id='input1', transcript='你好')
        self.assertEqual(await self.client.receive(), dict(type='transcript', text='你好', utterance_id=uid, generation=7))
        self.assertIsNone(self.store.get(self.owner))
        with self.store.transaction(self.owner):
            pass
        self.bridge.fence.check()
        self.assertEqual(self.store.get(self.owner)['messages'], [])

    async def test_short_sentences_are_checked_and_released_in_order(self):
        first = await self.speak('第一句。')
        second = str(uuid4())
        await self.client.send('speak', text='第二句。', speech_id=second)
        await self.provider.event('response.created', response={'id': 'r1'})
        await self.provider.event('response.audio.delta', response_id='r1', delta=PCM)
        await self.provider.event('response.audio_transcript.delta', response_id='r1', delta='第一句。')
        await asyncio.sleep(.01)
        self.assertTrue(self.client.output.empty(), 'Unverified audio must remain in memory')
        await self.provider.event('response.done', response={'id': 'r1'})
        self.assertEqual((await self.client.receive())['speech_id'], first)
        self.assertEqual(await self.client.receive(), dict(type='speech_done', speech_id=first))
        await self.provider.command('response.create')
        await self.provider.event('response.created', response={'id': 'r2'})
        await self.finish_response('r2', '第二句。')
        self.assertEqual((await self.client.receive())['speech_id'], second)
        self.assertEqual((await self.client.receive())['type'], 'speech_done')

    async def test_interrupt_is_responsive_while_next_sentence_waits_and_drops_late_audio(self):
        await self.speak('旧句。')
        await self.provider.event('response.created', response={'id': 'old'})
        await self.client.send('speak', text='排队句。', speech_id=str(uuid4()))
        await self.client.send('interrupt')
        await self.provider.command('response.cancel')
        uid = await self.commit(2)  # Input was not blocked by a waiting readout.
        await self.provider.event('input_audio_buffer.committed', item_id='new-input')
        await self.provider.event('conversation.item.input_audio_transcription.completed', item_id='new-input', transcript='新话')
        self.assertEqual((await self.client.receive())['utterance_id'], uid)
        fresh = str(uuid4())
        await self.client.send('speak', text='新句。', speech_id=fresh)
        await self.finish_response('old', '旧句。')
        await self.provider.command('response.create')
        await self.provider.event('response.created', response={'id': 'fresh'})
        await self.provider.event('response.audio.delta', response_id='old', delta=PCM)
        await self.finish_response('fresh', '新句。')
        self.assertEqual((await self.client.receive())['speech_id'], fresh)
        self.assertEqual(await self.client.receive(), dict(type='speech_done', speech_id=fresh))
        self.assertTrue(self.client.output.empty())

    async def test_interrupt_before_response_created_still_cancels_it(self):
        await self.speak('旧句。')
        await self.client.send('interrupt')
        await self.client.send('clear', cancel_transcripts=False)
        await self.provider.command('input_audio_buffer.clear')
        await self.provider.event('response.created', response={'id': 'late-created'})
        await self.provider.command('response.cancel')
        await self.finish_response('late-created', '旧句。')
        fresh = await self.speak('新句。')
        await self.provider.event('response.created', response={'id': 'fresh'})
        await self.finish_response('fresh', '新句。')
        self.assertEqual((await self.client.receive())['speech_id'], fresh)

    async def test_clear_keeps_late_ack_slot_but_suppresses_old_transcript(self):
        await self.commit()
        await self.client.send('clear')
        await self.provider.command('input_audio_buffer.clear')
        new = await self.commit(2)
        for item in ('old', 'new'):
            await self.provider.event('input_audio_buffer.committed', item_id=item)
            await self.provider.event('conversation.item.input_audio_transcription.completed', item_id=item, transcript=item)
        self.assertEqual(await self.client.receive(), dict(type='transcript', text='new', utterance_id=new, generation=2))
        self.assertTrue(self.client.output.empty())

    async def test_interrupt_during_checked_audio_delivery_does_not_cancel_completed_provider(self):
        sid = await self.speak('一句。')
        await self.provider.event('response.created', response={'id': 'done'})
        delivered, release = asyncio.Event(), asyncio.Event()
        original = self.client.send_json
        async def paused_send(event):
            await original(event)
            if event['type'] == 'audio':
                delivered.set()
                await release.wait()
        self.client.send_json = paused_send
        await self.finish_response('done', '一句。')
        await asyncio.wait_for(delivered.wait(), 1)
        await self.client.send('interrupt')
        await self.client.send('clear', cancel_transcripts=False)
        await self.provider.command('input_audio_buffer.clear')
        self.assertIsNone(self.bridge.response_id)
        self.assertFalse(self.bridge.cancel_sent)
        release.set()
        self.assertEqual((await self.client.receive())['speech_id'], sid)
        await asyncio.sleep(.01)
        self.assertTrue(self.client.output.empty(), 'Cancelled delivery must not emit speech_done')

    async def test_mute_and_interrupt_preserve_committed_transcript(self):
        uid = await self.commit(8)
        await self.client.send('interrupt')
        await self.client.send('clear', cancel_transcripts=False)
        await self.provider.command('input_audio_buffer.clear')
        await self.provider.event('input_audio_buffer.committed', item_id='kept')
        await self.provider.event('conversation.item.input_audio_transcription.completed', item_id='kept', transcript='保留')
        self.assertEqual((await self.client.receive())['utterance_id'], uid)

    async def test_empty_transcript_completes_without_fabricating_text(self):
        uid = await self.commit()
        await self.provider.event('input_audio_buffer.committed', item_id='silent')
        await self.provider.event('conversation.item.input_audio_transcription.completed', item_id='silent', transcript='  ')
        self.assertEqual(await self.client.receive(), dict(type='transcript', text='', utterance_id=uid, generation=1))
        self.assertIsNone(self.store.get(self.owner))

    async def test_mismatched_readout_is_blocked_with_identity_and_next_sentence_works(self):
        sid = await self.speak('问题是什么？')
        await self.provider.event('response.created', response={'id': 'wrong'})
        await self.finish_response('wrong', '这是答案。')
        self.assertEqual(await self.client.receive(), dict(type='speech_blocked', speech_id=sid, code='RT.AGENT.VOICE_SPEECH_MISMATCH'))
        fresh = await self.speak('下一句。')
        await self.provider.event('response.created', response={'id': 'new'})
        await self.finish_response('new', '下一句。')
        self.assertEqual((await self.client.receive())['speech_id'], fresh)

    async def test_owner_change_closes_idle_connection_without_more_input(self):
        with self.store.transaction(self.owner) as data:
            data['lifecycle_revision'] = 2
        with self.assertRaisesRegex(v.VoiceFailure, 'OWNER_CHANGED'):
            await asyncio.wait_for(self.running, 1)

    async def test_malformed_audio_is_rejected_before_provider_receives_it(self):
        await self.client.send('audio', audio=base64.b64encode(b'x').decode())
        with self.assertRaisesRegex(v.VoiceFailure, 'INVALID_PCM'):
            await asyncio.wait_for(self.running, 1)

    async def test_total_pcm_limit_applies_across_chunks(self):
        with patch.object(v, 'MAX_UTTERANCE_BYTES', 640):
            for _ in range(3):
                await self.client.send('audio', audio=PCM)
            with self.assertRaisesRegex(v.VoiceFailure, 'INPUT_LIMIT'):
                await asyncio.wait_for(self.running, 1)

    async def test_pending_sentence_queue_is_bounded_without_blocking_control(self):
        await self.speak('正在生成。')
        for _ in range(v.MAX_PENDING + 1):
            await self.client.send('speak', text='等待播报。', speech_id=str(uuid4()))
        with self.assertRaisesRegex(v.VoiceFailure, 'SPEECH_BACKLOG'):
            await asyncio.wait_for(self.running, 1)

    async def test_pending_bound_is_enforced_and_cancelled_ack_slots_stay_bounded(self):
        for _ in range(v.MAX_PENDING):
            await self.commit()
            await self.client.send('clear')
            await self.provider.command('input_audio_buffer.clear')
        await self.client.send('audio', audio=PCM)
        await self.client.send('commit_audio', utterance_id=str(uuid4()), generation=2)
        with self.assertRaisesRegex(v.VoiceFailure, 'INPUT_BACKLOG'):
            await asyncio.wait_for(self.running, 1)

    async def test_usage_retains_only_anonymous_numeric_totals(self):
        self.bridge.add_usage({'input_tokens': 4, 'total_tokens': 5, 'text': 'private', 'output_tokens': 'secret'})
        self.bridge.save_usage(self.store)
        with self.store.tasks._connection() as db:
            columns = [row[1] for row in db.execute('PRAGMA table_info(agent_voice_usage)')]
            row = db.execute('SELECT * FROM agent_voice_usage').fetchone()
        self.assertEqual(columns, ['model', 'duration_ms', 'calls', 'input_bytes', 'output_bytes', 'usage'])
        self.assertEqual(json.loads(row[-1]), {'input_tokens': 4, 'total_tokens': 5})
        self.assertNotIn(self.owner, repr(row))
        self.assertIsNone(self.store.get(self.owner))


class AgentVoiceRouteContracts(unittest.TestCase):
    def test_draft_allowed_without_creation_but_archived_deleted_and_foreign_origin_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(HarnessStore(tmp + '/voice.sqlite3'))
            draft, archived, deleted = [str(uuid4()) for _ in range(3)]
            with store.transaction(archived) as data:
                data['status'] = 'archived'
            store.delete(deleted, str(uuid4()), 1)
            app = FastAPI()
            app.include_router(v.router)
            with patch.object(v, 'conversation_store', store), patch.object(v, 'configuration', side_effect=ValueError), TestClient(app) as client:
                with client.websocket_connect(f'/v2/agent/voice/{draft}/audio') as ws:
                    self.assertEqual(ws.receive_json(), dict(type='error', code='RT.AGENT.VOICE_NOT_CONFIGURED'))
                self.assertIsNone(store.get(draft))
                for owner, headers in ((archived, {}), (deleted, {}), (draft, {'origin': 'https://example.com'})):
                    with self.assertRaises(WebSocketDisconnect):
                        with client.websocket_connect(f'/v2/agent/voice/{owner}/audio', headers=headers):
                            pass


if __name__ == '__main__':
    unittest.main()
