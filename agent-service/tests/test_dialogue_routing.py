"""A006 sanitized reproductions and adjacent dialogue state regressions."""
import copy
import unittest
from tests import test_conversation_v2 as f
from agent_service.schemas import ConversationOutput, IntentDecision

class DialogueRoutingTests(unittest.TestCase):
    def setUp(self):
        self.f = f.ConversationTests(); self.f.setUp()
    def tearDown(self): self.f.tearDown()

    def test_auto_question_scope_conflict_after_greeting_cannot_create_task(self):
        self.f.decision = f.intent('greeting', light_reply='你好，想了解什么？')
        self.f.send('你好')
        self.f.decision = f.intent('defer', light_reply='没关系，想到问题可以告诉我。')
        self.f.send('我不知道')
        self.f.decision = f.intent('question', scope='learning', workflow='topic_exploration').model_copy(update={'relation':'new_topic'})
        accepted = self.f.send('harness是什么，它有什么作用')
        state = self.f.state()
        self.assertFalse(state['tasks'])
        self.assertIsNone(state['pending'])
        self.assertTrue(state['runs'][accepted.run_id]['intent']['answer_only'])
        self.assertFalse(any(e['node']=='clarify_goal' for e in state['events']))
        self.assertIn('直接回答', [p for s,p in self.f.calls if s is ConversationOutput][-1]['instruction'])

    def test_new_topic_question_does_not_force_session_choice(self):
        self.f.decision = f.intent('question', answer_only=True)
        self.f.send('RAG 是什么')
        self.f.decision = f.intent('question', scope='learning', workflow='topic_exploration').model_copy(update={'relation':'new_topic'})
        self.f.send('吉他的和弦是什么')
        self.assertIsNone(self.f.state()['pending'])
        self.assertFalse(self.f.state()['tasks'])

    def seed_goal_clarification(self, *, misrouted):
        self.f.decision = f.intent('goal', scope='learning', workflow='topic_exploration')
        accepted = self.f.send('harness是什么，它有什么作用' if misrouted else '带我系统学习 harness')
        if misrouted:
            with self.f.store.transaction(self.f.sid) as d:
                d['runs'][accepted.run_id]['intent'] = f.intent('question', scope='learning', workflow='topic_exploration').model_dump()
        return next(iter(self.f.state()['tasks']))

    def test_repair_retires_only_legacy_unstarted_question_task(self):
        tid = self.seed_goal_clarification(misrouted=True)
        self.f.decision = f.intent('correction', conversation_repair=True)
        accepted = self.f.send('我只是问它是什么，先回答问题')
        state = self.f.state()
        self.assertEqual(state['tasks'][tid]['status'], 'cancelled')
        self.assertIsNone(state['tasks'][tid]['required_action'])
        self.assertIsNone(state['active_task_id'])
        self.assertEqual(state['runs'][accepted.run_id]['resolved_input'], 'harness是什么，它有什么作用')
        self.f.capture.assert_not_called()

    def test_plain_followup_also_unblocks_legacy_question_task(self):
        tid = self.seed_goal_clarification(misrouted=True)
        self.f.decision = f.intent('example', scope='learning', workflow='source_learning')
        self.f.send('举个实际例子解释一下')
        self.assertEqual(self.f.state()['tasks'][tid]['status'], 'cancelled')
        self.assertIsNone(self.f.state()['active_task_id'])
        self.assertEqual(len(self.f.state()['tasks']), 1)

    def test_repair_does_not_retire_explicit_learning_goal(self):
        tid = self.seed_goal_clarification(misrouted=False)
        before = copy.deepcopy(self.f.state()['tasks'][tid])
        self.f.decision = f.intent('correction', conversation_repair=True)
        self.f.send('你误会了，先回答我的问题')
        self.assertEqual(self.f.state()['tasks'][tid], before)

    def test_local_question_preserves_real_learning_progress(self):
        self.f.decision = f.intent('goal', scope='learning', workflow='source_learning', direct_teaching=True)
        self.f.send('带我系统学习 RAG')
        tid = self.f.state()['active_task_id']
        before = copy.deepcopy(self.f.state()['tasks'][tid])
        self.f.decision = f.intent('question', scope='learning', workflow='topic_exploration')
        self.f.send('刚才的检索是什么意思')
        after = self.f.state()['tasks'][tid]
        self.assertEqual(after['stage'], before['stage'])
        self.assertEqual(after['context']['learning_plan'], before['context']['learning_plan'])
        self.assertEqual(after['required_action'], before['required_action'])

    def test_non_auto_selected_workflow_is_preserved(self):
        self.f.decision = f.intent('greeting')
        self.f.send('你好')
        with self.f.store.transaction(self.f.sid) as d:
            d['mode'] = 'topic_exploration'
        self.f.decision = f.intent('question', scope='learning', workflow='topic_exploration')
        self.f.send('harness 是什么')
        self.assertEqual(next(iter(self.f.state()['tasks'].values()))['stage'], 'clarify_goal')

    def test_independent_question_uncertain_relation_still_answers(self):
        self.f.decision=f.intent('question', answer_only=True).model_copy(update={'relation':'uncertain'})
        self.f.send('什么叫 harness')
        self.assertTrue(any(s is ConversationOutput for s,_ in self.f.calls))
        self.assertNotIn('继续刚才', self.f.state()['messages'][-1]['content'])
        self.assertFalse(self.f.state()['tasks'])
    def test_router_does_not_receive_external_memory_bodies(self):
        self.f.decision=f.intent('question',answer_only=True)
        body=f.SessionMessageRequest(client_message_id=str(f.uuid.uuid4()),content='什么叫 harness',context={'memory_candidates':[{'id':'old','knowledge_id':'known-card','kind':'formal','concept':'旧概念','excerpt':'旧的秘密学习正文'}]})
        self.f.harness.accept(self.f.sid,body); self.f.harness.drain(self.f.sid)
        prompt=next(p for s,p in self.f.calls if s is IntentDecision)
        self.assertNotIn('旧的秘密学习正文', str(prompt))
    def test_conversation_repair_returns_to_unanswered_question(self):
        self.f.decision=f.intent('question',clarification='你希望继续刚才的内容，还是开始一个新的学习问题？').model_copy(update={'relation':'uncertain','clarification_kind':'resume_target'})
        self.f.send('什么叫 harness')
        # Emulate the legacy incorrect clarification shown in the actual screenshot.
        with self.f.store.transaction(self.f.sid) as d:
            d['messages'][-1]['content']='你希望继续刚才的内容，还是开始一个新的学习问题？'
        self.f.decision=f.intent('correction', reply_feedback='with_request').model_copy(update={'conversation_repair':True})
        before=copy.deepcopy(self.f.state()['tasks'])
        self.f.send('我不是才和你聊天吗')
        answers=[p for s,p in self.f.calls if s is ConversationOutput]
        self.assertIn('纠正',answers[-1]['instruction'])
        self.assertIn('什么叫 harness',str(answers[-1]))
        self.assertEqual(before,self.f.state()['tasks'])
    def test_specific_content_clarification_is_allowed_once(self):
        self.f.decision=f.intent('question',clarification='你指哪个领域的接口？').model_copy(update={'clarification_kind':'content'})
        self.f.send('这个接口怎么用')
        self.assertEqual(self.f.state()['messages'][-1]['content'],'你指哪个领域的接口？')
        self.f.send('就这个啊')
        self.assertTrue(any(s is ConversationOutput for s,_ in self.f.calls))
    def test_state_change_clarification_is_not_auto_confirmed(self):
        self.f.decision=f.intent('confirm',clarification='你希望保存哪一版？').model_copy(update={'clarification_kind':'operation'})
        self.f.send('保存那个')
        self.assertEqual(self.f.state()['messages'][-1]['content'],'你希望保存哪一版？')
        self.f.capture.assert_not_called()

    def test_second_legacy_rephrase_still_repairs_original_question(self):
        self.f.decision=f.intent('question',answer_only=True)
        self.f.send('什么叫 harness')
        with self.f.store.transaction(self.f.sid) as d:
            d['messages'][-1]['content']='你希望继续刚才的内容，还是开始一个新的学习问题？'
        self.f.send('我不是才和你聊天吗')
        with self.f.store.transaction(self.f.sid) as d:
            d['messages'][-1]['content']='你是想继续问“什么叫 harness”，还是想接着之前的话题？'
        self.f.decision=f.intent('question',conversation_repair=True,repair_target_message_id='invalid-other-session')
        accepted=self.f.send('这是新会话，你又理解错了')
        self.assertEqual(self.f.state()['runs'][accepted.run_id]['resolved_input'],'什么叫 harness')
        self.assertFalse(self.f.state()['tasks'])
