"""A007 synthetic cross-session ownership, consent and recovery regressions."""
import copy
from dataclasses import asdict
import json
import unittest
import uuid
from unittest.mock import patch
from tests import test_conversation_v2 as fixtures
from tests.test_conversation_v2 import intent
from agent_service.schemas import SessionMessageRequest
from agent_service.harness_store import HarnessTaskRecord, StaleExecution
from agent_service.conversation_store import ConversationStore, Superseded
from agent_service.conversation import ConversationHarness
from agent_service.learning_progress import set_plan
from agent_service.goal_continuation import ContinuationChoice, ContinuationRequest, candidates, transfer, owns, ownership

class GoalContinuationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ConversationTests(); self.f.setUp()
        self.base=self.f.model
        def model(system,user,schema,**kw):
            if schema is ContinuationRequest:
                return ContinuationRequest(evidence=json.loads(user)['request'],topic='RAG')
            if schema is ContinuationChoice:
                entries=json.loads(user)['candidates']
                return ContinuationChoice(matching_task_ids=[x['task_id'] for x in entries])
            return self.base(system,user,schema,**kw)
        self.patch=patch('agent_service.conversation.parse_model',side_effect=model); self.patch.start()
    def tearDown(self):
        self.patch.stop(); self.f.tearDown()
    def seed(self, archived=False):
        sid,tid=str(uuid.uuid4()),str(uuid.uuid4())
        task=asdict(HarnessTaskRecord(task_id=tid,session_id=sid,client_message_id=str(uuid.uuid4()),
            content='理解 RAG',content_type='text',primary_language='zh',mode_preset='auto',mode='source_learning',
            status='awaiting_user',stage='teaching',context={'conversation_managed':True,'understanding':'unknown',
            'draft':{'secret':'old consent'},'held_commit':{'secret':'old commit'},'commit_claimed':True}))
        set_plan(task,['理解检索','理解生成','验证答案'])
        task['context']['learning_plan']['steps'][0].update(state='explained',message_ids=[str(uuid.uuid4())])
        with self.f.store.transaction(sid) as d:
            d['tasks'][tid]=task; d['active_task_id']=tid
            d['status']='archived' if archived else 'active'
            d['pending']={'kind':'save','consent_received':True}; d['draft']={'secret':'old draft'}
        self.f.harness.memory_policy(sid,allowed=True,policy_version=0,content_version=0)
        return sid,tid
    def resume(self,text='继续上次没学完的 RAG'):
        self.f.decision=intent('continue',scope='continue_goal',continuation_evidence=text,continuation_topic='RAG')
        return self.f.send(text)
    def test_unique_goal_moves_owner_preserves_plan_not_consent(self):
        sid,tid=self.seed(); before=self.f.store.get(sid)['tasks'][tid]
        self.resume()
        dest=self.f.state(); new=dest['tasks'][dest['active_task_id']]
        old=self.f.store.get(sid)['tasks'][tid]
        self.assertTrue(owns(new)); self.assertFalse(owns(old))
        self.assertEqual(ownership(new)['goal_id'],tid)
        self.assertEqual([s['id'] for s in before['context']['learning_plan']['steps']], [s['id'] for s in new['context']['learning_plan']['steps']])
        self.assertEqual(new['context']['learning_plan']['current_step_id'],before['context']['learning_plan']['steps'][1]['id'])
        self.assertFalse(any(k in new['context'] for k in ('draft','held_commit','commit_claimed')))
        self.assertIsNone(dest['pending']); self.f.capture.assert_not_called()
    def test_ordinary_question_does_not_resume_old_goal(self):
        sid,tid=self.seed(); self.f.decision=intent('question',answer_only=True)
        self.f.send('什么叫 harness'); self.assertFalse(self.f.state()['tasks'])
        self.assertTrue(owns(self.f.store.get(sid)['tasks'][tid]))
    def test_archived_source_stays_archived_and_history_is_unchanged(self):
        sid,tid=self.seed(archived=True); before=self.f.store.get(sid)
        self.resume(); after=self.f.store.get(sid)
        self.assertEqual(after['status'],'archived'); self.assertEqual(after['messages'],before['messages'])
        self.assertFalse(owns(after['tasks'][tid]))
    def test_multiple_and_none_do_not_create_progress(self):
        self.seed(); self.seed(); self.resume('继续上次学习')
        self.assertFalse(self.f.state()['tasks']); self.assertIn('哪一个',self.f.state()['messages'][-1]['content'])
    def test_excluded_and_stale_native_candidates_not_resumed(self):
        sid,tid=self.seed(); self.f.harness.memory_policy(sid,allowed=False,policy_version=1,content_version=0)
        self.resume(); self.assertFalse(self.f.state()['tasks'])
        self.assertIn('没有找到',self.f.state()['messages'][-1]['content'])
        self.f.harness.memory_policy(sid,allowed=True,policy_version=2,content_version=0)
        self.f.decision=intent('continue',scope='continue_goal',continuation_evidence='继续上次学习')
        request=SessionMessageRequest(client_message_id=str(uuid.uuid4()),content='继续上次学习',context={'continuation_candidates':[dict(task_id=tid,policy_version=0,content_version=0,owner_version=1)]})
        self.f.harness.accept(self.f.sid,request);self.f.harness.drain(self.f.sid)
        self.assertFalse(self.f.state()['tasks'])
    def test_source_busy_not_stolen(self):
        sid,tid=self.seed()
        self.f.send('继续',sid=sid,drain=False)
        self.resume();self.assertFalse(self.f.state()['tasks']);self.assertTrue(owns(self.f.store.get(sid)['tasks'][tid]))
        self.assertIn('还在处理',self.f.state()['messages'][-1]['content'])
    def test_replayed_acceptance_and_restart_do_not_duplicate_owner(self):
        sid,tid=self.seed(); self.resume()
        data=self.f.state(); first=next(iter(data['messages'])); run=data['runs'][first['run_id']]
        self.f.harness=ConversationHarness(ConversationStore(self.f.tasks));self.f.harness.recover()
        self.assertEqual(len(self.f.state()['tasks']),1)
        self.assertEqual(sum(owns(t) for s in self.f.store.sessions() for t in self.f.store.get(s)['tasks'].values()),1)
    def test_stale_legacy_save_and_snapshot_cannot_resurrect_source(self):
        sid,tid=self.seed(); stale=HarnessTaskRecord(**copy.deepcopy(self.f.store.get(sid)['tasks'][tid]))
        snapshot=self.f.harness.export_snapshot(sid); self.resume()
        with self.assertRaises(StaleExecution): self.f.tasks.save(stale)
        # Simulate source checkpoint missing while the durable destination survived.
        with self.f.tasks._connection() as db:
            db.execute('DELETE FROM agent_sessions_v2 WHERE session_id=?',(sid,))
            db.execute('DELETE FROM harness_tasks WHERE session_id=?',(sid,))
        self.f.harness.restore_snapshot(sid,snapshot)
        self.assertFalse(owns(self.f.store.get(sid)['tasks'][tid]))
        self.assertIsNone(self.f.store.get(sid)['active_task_id'])
    def test_version_changed_during_matching_does_not_transfer(self):
        sid,tid=self.seed(); normal=self.f.harness._call
        def race(*args,**kwargs):
            result=normal(*args,**kwargs)
            if args[3]=='continuation_match':
                with self.f.store.transaction(sid) as d: d['tasks'][tid]['context']['understanding']='self_reported'
            return result
        with patch.object(self.f.harness,'_call',side_effect=race): self.resume()
        self.assertFalse(self.f.state()['tasks']);self.assertIn('发生了变化',self.f.state()['messages'][-1]['content'])
    def test_restoring_new_owner_demotes_existing_old_checkpoint(self):
        sid,tid=self.seed(); old_snapshot=self.f.harness.export_snapshot(sid)
        self.resume(); destination=self.f.harness.export_snapshot(self.f.sid)
        with self.f.tasks._connection() as db:
            db.execute('DELETE FROM agent_sessions_v2'); db.execute('DELETE FROM harness_tasks')
        self.f.harness.restore_snapshot(sid,old_snapshot)
        self.assertTrue(owns(self.f.store.get(sid)['tasks'][tid]))
        self.f.harness.restore_snapshot(self.f.sid,destination)
        self.assertFalse(owns(self.f.store.get(sid)['tasks'][tid]))
        self.assertIsNone(self.f.store.get(sid)['active_task_id'])
    def test_deleted_source_is_not_resumed(self):
        sid,tid=self.seed(archived=True); self.f.store.delete(sid,str(uuid.uuid4()),1)
        self.resume();self.assertFalse(self.f.state()['tasks'])
    def test_retry_after_transfer_neither_copies_nor_advances_twice(self):
        from agent_service.schemas import ConversationOutput
        sid,tid=self.seed(); normal=self.f.harness._call
        def fail(*args,**kwargs):
            if args[3]=='lesson': raise RuntimeError('synthetic coach failure')
            return normal(*args,**kwargs)
        with patch.object(self.f.harness,'_call',side_effect=fail): run=self.resume()
        state=self.f.state();task=next(iter(state['tasks'].values()));step=task['context']['learning_plan']['current_step_id']
        self.assertEqual(state['runs'][run.run_id]['status'],'retryable_failed')
        self.f.control(run.run_id,'retry');self.f.harness.drain(self.f.sid)
        task=next(iter(self.f.state()['tasks'].values()))
        self.assertEqual(task['context']['learning_plan']['current_step_id'],step)
        self.assertEqual(len(self.f.state()['tasks']),1);self.assertEqual(ownership(task)['version'],2)
        self.assertEqual(self.f.state()['runs'][run.run_id]['status'],'completed')
    def test_source_exclusion_after_transfer_invalidates_derived_context(self):
        sid,tid=self.seed();self.resume()
        self.f.harness.memory_policy(sid,allowed=False,policy_version=1,content_version=0)
        run=next(iter(self.f.state()['runs'].values()))
        self.assertFalse(self.f.harness._memory_run_valid(run))
    def test_quoted_resume_evidence_cannot_transfer(self):
        sid,tid=self.seed();self.f.decision=intent('question',answer_only=True,continuation_evidence='继续上次学习')
        self.f.send('解释这句话：“继续上次学习”')
        self.assertFalse(self.f.state()['tasks']);self.assertTrue(owns(self.f.store.get(sid)['tasks'][tid]))
    def test_two_destinations_cannot_both_acquire_source(self):
        sid,tid=self.seed(); normal=self.f.harness._call; other=str(uuid.uuid4()); invoked=False
        def race(*args,**kwargs):
            nonlocal invoked
            result=normal(*args,**kwargs)
            if args[3]=='continuation_match' and not invoked:
                invoked=True;self.f.send('继续上次没学完的 RAG',sid=other)
            return result
        with patch.object(self.f.harness,'_call',side_effect=race): self.resume()
        self.assertFalse(self.f.state()['tasks']);self.assertEqual(len(self.f.store.get(other)['tasks']),1)
        self.assertFalse(owns(self.f.store.get(sid)['tasks'][tid]))
    def test_continue_in_old_history_does_not_duplicate_progress(self):
        sid,tid=self.seed();self.resume()
        self.f.decision=intent('continue',scope='continue_goal')
        self.f.send('继续',sid=sid)
        old=self.f.store.get(sid)
        self.assertEqual(len(old['tasks']),1);self.assertFalse(owns(old['tasks'][tid]))
        self.assertIn('前往查看',old['messages'][-1]['content'])

    def test_missing_resume_field_never_invents_new_goal(self):
        self.f.decision=intent('continue',scope='continue_goal',workflow='source_learning',learning_goal_ready=True)
        self.f.send('继续上次没学完的光合作用')
        self.assertFalse(self.f.state()['tasks']);self.assertIn('没有找到',self.f.state()['messages'][-1]['content'])

    def test_next_topic_content_clarification_does_not_query_old_goals(self):
        for old_goal in (False, True):
            for scope in ('conversation', 'continue_goal'):
                with self.subTest(old_goal=old_goal, scope=scope):
                    self.f.sid=str(uuid.uuid4())
                    source=self.seed() if old_goal else None
                    self.f.decision=intent('question',answer_only=True)
                    self.f.send('大模型是如何生成回复的？')
                    answer=self.f.state()['messages'][-1]
                    history=copy.deepcopy(self.f.state()['messages'])
                    clarification='好，这一段先到这里。接下来想了解什么？'
                    self.f.decision=intent('continue',scope=scope,
                        clarification_kind='content',clarification=clarification,
                        topic_closure=dict(evidence='好的，先这样吧',title='语言模型生成回复',
                            message_ids=[answer['message_id']],next_request='我们学下一个内容'))
                    with patch.object(self.f.harness,'_call',wraps=self.f.harness._call) as calls, \
                         patch('agent_service.goal_continuation.candidates',wraps=candidates) as query:
                        result=self.f.send('好的，先这样吧，我们学下一个内容')
                    state=self.f.state()
                    self.assertEqual(state['runs'][result.run_id]['status'],'completed')
                    self.assertEqual(state['messages'][-1]['content'],clarification)
                    self.assertEqual(state['messages'][:len(history)],history)
                    self.assertFalse(state['tasks']);self.assertFalse(state.get('capture_offers'))
                    self.assertEqual([c.args[3] for c in calls.call_args_list],['intent'])
                    query.assert_not_called();self.f.capture.assert_not_called()
                    if source:
                        self.assertTrue(owns(self.f.store.get(source[0])['tasks'][source[1]]))

    def test_local_continue_uses_current_dialogue_without_recovery(self):
        source,tid=self.seed()
        self.f.decision=intent('question',answer_only=True)
        self.f.send('请介绍大模型生成回答的原理')
        self.f.decision=intent('continue',scope='conversation')
        with patch.object(self.f.harness,'_call',wraps=self.f.harness._call) as calls:
            self.f.send('接着解释第二点')
        self.assertEqual(self.f.state()['messages'][-1]['content'],'这是本轮真实回答。')
        self.assertFalse(self.f.state()['tasks'])
        self.assertFalse(any(c.args[3].startswith('continuation_') for c in calls.call_args_list))
        self.assertTrue(owns(self.f.store.get(source)['tasks'][tid]))

    def test_next_step_preserves_current_plan_and_ownership(self):
        sid,tid=self.seed()
        before=copy.deepcopy(self.f.store.get(sid)['tasks'][tid])
        self.f.decision=intent('continue',scope='continue_goal',target_task_id=tid)
        with patch.object(self.f.harness,'_call',wraps=self.f.harness._call) as calls:
            result=self.f.send('好的，先这样吧，我们学下一个内容',sid=sid)
        data=self.f.store.get(sid);after=data['tasks'][tid]
        self.assertEqual(data['runs'][result.run_id]['status'],'completed')
        self.assertEqual(data['active_task_id'],tid);self.assertEqual(len(data['tasks']),1)
        self.assertEqual(ownership(after),ownership(before))
        self.assertEqual(after['context']['understanding'],'unknown')
        self.assertEqual([s['id'] for s in after['context']['learning_plan']['steps']],
                         [s['id'] for s in before['context']['learning_plan']['steps']])
        self.assertTrue(any(c.args[3]=='lesson' for c in calls.call_args_list))
        self.assertFalse(any(c.args[3].startswith('continuation_') for c in calls.call_args_list))

    def test_local_topic_question_in_transferred_history_is_not_redirected(self):
        sid,tid=self.seed();self.resume()
        self.f.decision=intent('continue',scope='conversation',clarification_kind='content',
                              clarification='接下来想了解什么？')
        self.f.send('我们学下一个内容',sid=sid)
        data=self.f.store.get(sid)
        self.assertEqual(data['messages'][-1]['content'],'接下来想了解什么？')
        self.assertFalse(owns(data['tasks'][tid]))

    def test_negative_recovery_returns_to_current_dialogue(self):
        self.f.decision=intent('question',answer_only=True)
        self.f.send('大模型如何生成回答？')
        self.f.decision=intent('continue',scope='continue_goal',direct_teaching=True,
                              workflow='source_learning',learning_goal_ready=True)
        normal=self.f.harness._call
        def model(*args,**kwargs):
            if args[3]=='continuation_intent':
                context=json.loads(args[5])
                self.assertIn('recent_messages',context)
                self.assertNotIn('memory_candidates',context)
                return ContinuationRequest(evidence='',topic='')
            return normal(*args,**kwargs)
        with patch.object(self.f.harness,'_call',side_effect=model):
            self.f.send('接着说')
        self.assertFalse(self.f.state()['tasks'])
        self.assertEqual(self.f.state()['messages'][-1]['content'],'这是本轮真实回答。')

    def test_continuation_recovery_does_not_swallow_an_explicit_operation(self):
        self.f.decision=intent('continue',scope='continue_goal',requested_mode='source_learning',
            proposed_actions=[dict(kind='set_mode',disposition='request',evidence='切换到资料学习')])
        with patch.object(self.f.harness,'_call',wraps=self.f.harness._call) as calls:
            self.f.send('继续之前，先切换到资料学习')
        self.assertEqual(self.f.state()['mode'],'source_learning')
        self.assertFalse(self.f.state()['tasks'])
        self.assertFalse(any(c.args[3].startswith('continuation_') for c in calls.call_args_list))

    def test_atomic_failure_keeps_source_owner_and_creates_no_destination(self):
        sid,tid=self.seed()
        with self.f.tasks._connection() as db:
            db.execute("CREATE TRIGGER fail_goal_transfer BEFORE INSERT ON harness_tasks WHEN NEW.session_id = '"+self.f.sid+"' BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END")
        self.resume()
        self.assertTrue(owns(self.f.store.get(sid)['tasks'][tid]))
        self.assertFalse(self.f.state()['tasks'])
        self.assertEqual(self.f.store.get(sid)['active_task_id'],tid)
    def test_transfer_does_not_refresh_unrelated_historical_tasks(self):
        sid,tid=self.seed()
        with self.f.store.transaction(sid) as d:
            other=copy.deepcopy(d['tasks'][tid]);other['task_id']=str(uuid.uuid4());other['client_message_id']=str(uuid.uuid4());other['status']='completed'
            d['tasks'][other['task_id']]=other
        stamp=self.f.store.get(sid)['tasks'][other['task_id']]['updated_at']
        self.resume()
        self.assertEqual(self.f.store.get(sid)['tasks'][other['task_id']]['updated_at'],stamp)

    def test_context_repair_precedes_resume_classification(self):
        sid,tid=self.seed()
        self.f.decision=intent('question',answer_only=True);self.f.send('什么叫 harness')
        self.f.decision=intent('continue',conversation_repair=True,continuation_evidence='继续上次学习')
        self.f.send('我不是要求继续上次学习，我才刚开始问')
        self.assertFalse(self.f.state()['tasks']);self.assertTrue(owns(self.f.store.get(sid)['tasks'][tid]))
        self.assertTrue(list(self.f.state()['runs'].values())[-1]['dialogue_only'])
