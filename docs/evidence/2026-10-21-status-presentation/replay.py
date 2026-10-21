"""Reapply the retained real intent to an isolated harness, without network.

This is a controlled replay of the production route, not a new model decision.
"""
import copy
import json
from pathlib import Path
import socket
from unittest.mock import patch

OUT = Path(__file__).resolve().parent
REAL = OUT.parent / '2026-10-21-preview-save-real'


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def blocked(*args, **kwargs):
    raise AssertionError('Real networking is forbidden in the presentation replay')


def main():
    with patch.object(socket, 'create_connection', side_effect=blocked), patch.object(socket.socket, 'connect', side_effect=blocked):
        from agent_service.knowledge_capture_status import facts, reply
        from agent_service.schemas import IntentDecision
        from tests.test_conversation_v2 import ConversationTests
        data, final = read(REAL / 'save-check.json'), read(REAL / 'after-status-query.json')
        intent = list(final['runs'].values())[-1]['intent']
        query = final['messages'][-2]['content']
        before = copy.deepcopy(data)
        state = facts(data, related_knowledge=[dict(id='reference-only')],
            save_operation=intent['knowledge_save_operation'], current_request=query)
        corrected = reply(state, intent['status_context'])
        assert data == before
        assert '已成功写入 4 张知识卡' in corrected
        for index, card in enumerate(state['current_cards'], 1):
            assert f'{index}. {card["title"]}' in corrected
        assert all(x not in corrected for x in ('本次保存范围', '旧卡只是参考', '内容包括'))
        fixture = ConversationTests()
        fixture.setUp()
        try:
            fixture.sid = data['session_id']
            with fixture.store.transaction(fixture.sid) as target:
                target.update(copy.deepcopy(data))
            baseline = fixture.state()
            fixture.decision = IntentDecision.model_validate(intent)
            accepted = fixture.send(query, mode=data['mode'])
            after = fixture.state()
            assert after['runs'][accepted.run_id]['status'] == 'completed'
            assert after['messages'][-1]['content'] == corrected
            assert after['tasks'] == baseline['tasks'] and after['capture_offers'] == baseline['capture_offers']
            assert after['messages'][:len(data['messages'])] == data['messages']
            assert fixture.calls[0][0] is IntentDecision and len(fixture.calls) == 1
            fixture.capture.assert_not_called()
        finally:
            fixture.tearDown()
        write(OUT / 'reply-comparison.json', dict(layer='controlled_production_harness_replay',
            prior_real_reply=final['messages'][-1]['content'], corrected_reply=corrected,
            prior_characters=len(final['messages'][-1]['content']), corrected_characters=len(corrected),
            original_real_intent_reused=True, synthetic_model_reply=False, network_blocked=True,
            real_model_requests=0, real_web_operations=0, task_offer_and_prior_history_unchanged=True))
        (OUT / 'corrected-reply.txt').write_text(corrected + '\n')
        print(json.dumps(dict(outcome='PASS', prior_characters=len(final['messages'][-1]['content']),
            corrected_characters=len(corrected), real_model_requests=0, real_web_operations=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
