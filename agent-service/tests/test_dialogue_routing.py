"""A006 sanitized reproductions and adjacent dialogue state regressions."""
import copy
import unittest
from tests import test_conversation_v2 as f
from agent_service.schemas import ConversationOutput, IntentDecision

class DialogueRoutingTests(unittest.TestCase):
    def setUp(self):
        self.f = f.ConversationTests(); self.f.setUp()
    def tearDown(self): self.f.tearDown()
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
        self.f.decision=f.intent('correction').model_copy(update={'conversation_repair':True})
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
