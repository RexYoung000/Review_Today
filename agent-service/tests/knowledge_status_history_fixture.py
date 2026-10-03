"""Synthetic legacy history preserving the acceptance failure's causal sequence.

No user database or private snapshot is read. The wrong old answer and mismatched
plan are deliberate historical fixture data, not expected current behaviour.
"""
from dataclasses import asdict
import uuid


KEYWORD_ID = 'synthetic-keyword-lesson'
VECTOR_ID = 'synthetic-vector-feedback'
CLAIM_ID = 'synthetic-old-card-claim'
KEYWORD_QUOTE = '关键词检索主要按字词匹配，具体能否命中还取决于分词和匹配规则。'
VECTOR_QUOTE = '向量检索比对语义相近程度，措辞不同的内容也可能被召回，但不保证正确。'
CLAIM_QUOTE = '这个会话里已经记录了两张 RAG 知识卡'
QUERY = '刚才回答的知识点有没有生成卡片？'


def proposal():
    return dict(focus=[dict(label='关键词检索', message_id=KEYWORD_ID, quote=KEYWORD_QUOTE),
                       dict(label='向量检索', message_id=VECTOR_ID, quote=VECTOR_QUOTE)],
                prior_claim=dict(message_id=CLAIM_ID, quote=CLAIM_QUOTE, kind='recorded'))


def seed(harness, sid=None):
    from agent_service.conversation import _new_run
    from agent_service.harness_store import HarnessTaskRecord, now_iso
    from agent_service.learning_progress import set_plan

    sid, tid = sid or str(uuid.uuid4()), str(uuid.uuid4())
    task = asdict(HarnessTaskRecord(task_id=tid, session_id=sid,
        client_message_id=str(uuid.uuid4()), content='学习 RAG 的基础流程', content_type='text',
        primary_language='zh', mode_preset='source_learning', mode='source_learning',
        status='awaiting_user', stage='practice', context=dict(conversation_managed=True,
            understanding='verified', check_question='为什么向量索引可能找到措辞不同的段落？')))
    set_plan(task, ['资料切块', '检索流程'])
    task['context']['learning_plan']['steps'][0]['state'] = 'verified'
    status_intent = dict(intents=['capabilities'], relation='continuation', scope='conversation',
        reply_purpose='product_information', workflow=None, answer_only=True,
        direct_teaching=False, proposed_actions=[], rationale='合成旧状态回复')
    prefix = [
        ('直接教我 RAG。', 'synthetic-chunk-lesson',
         '先看资料切块：把文档分成便于检索的小段。为什么不把整本手册作为一个段落？',
         dict(activity_kind='lesson_step', learning_concepts=['资料切块'])),
        ('我不理解你的问题。', KEYWORD_ID,
         '刚才是在问整本手册一起检索有什么困难。接下来看关键词与向量匹配。' + KEYWORD_QUOTE +
         '文档写“如何安装电池”，用户搜“电池怎么装”，只用关键词检索可能会怎样？',
         dict(activity_kind='lesson_step', learning_concepts=['关键词检索', '向量检索'])),
        ('可能找到其他电池内容，因为电池这个词仍然可以匹配。', 'synthetic-legacy-negative-feedback',
         '这里要回答安装电池这段会漏掉。向量索引为什么可能找到这段？',
         dict(intent=dict(intents=['answer'], relation='continuation', scope='learning',
                          rationale='合成旧未绑定评价', answer_evidence='可能找到其他电池内容，因为电池这个词仍然可以匹配。'))),
        ('它可以比较装电池这个意思，而不只是相同的词。', VECTOR_ID,
         '回答正确。' + VECTOR_QUOTE + '这一节的理解检查已通过。',
         dict(intent=dict(intents=['answer'], relation='continuation', scope='learning',
                          rationale='合成旧未绑定评价', answer_evidence='它可以比较装电池这个意思，而不只是相同的词。'))),
        ('你有记录相关知识卡吗？', CLAIM_ID,
         '有的。' + CLAIM_QUOTE + '：一张讲“什么是检索增强生成及其核心机制”，'
         '一张讲“检索与生成阶段分别做什么”，都标注为前置知识。',
         dict(dialogue_only=True, intent=status_intent)),
        ('刚才的知识点有没有生成卡片？', 'synthetic-generic-status',
         '刚才的讲解和作答已留在聊天记录中，但这段内容还没有整理成知识卡。',
         dict(dialogue_only=True, knowledge_status_reply=True,
              intent=dict(status_intent, knowledge_card_status=True))),
    ]
    with harness.store.transaction(sid) as data:
        data.update(mode='source_learning', active_task_id=tid, focus_goal=task['content'])
        data.setdefault('capture_offers', {})
        data['tasks'][tid] = task
        for user, mid, coach, extra in prefix:
            uid = str(uuid.uuid4())
            run = _new_run(sid, uid, 'completed')
            run.update(extra)
            run.update(task_id=None if extra.get('dialogue_only') else tid,
                       execution_complete=True, completed_at=now_iso())
            data['runs'][run['run_id']] = run
            if extra.get('activity_kind') == 'lesson_step':
                task['context']['last_lesson'] = coach
                task['context']['learning_plan']['steps'][0]['message_ids'].append(mid)
            if 'answer' in (run.get('intent') or {}).get('intents', []):
                task['context'].setdefault('practice', []).append(dict(
                    message_id=uid, run_id=run['run_id'], revision=1, hint_used=False,
                    evaluation=dict(passed=mid == VECTOR_ID, feedback=coach,
                        correctness='正确' if mid == VECTOR_ID else '部分正确',
                        completeness='完整' if mid == VECTOR_ID else '待补充',
                        expression='清楚', transfer='待验证', followup_question='')))
            for role, identity, content in [('user', uid, user), ('coach', mid, coach)]:
                data['messages'].append(dict(message_id=identity, role=role, content=content,
                    content_type='text', input_channel='text', run_id=run['run_id'],
                    task_id=run['task_id'], created_at=now_iso(), context={}, operation=None))
    return sid
