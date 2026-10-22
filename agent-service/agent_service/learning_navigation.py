"""Returning to a learning task does not itself authorize moving its step."""
import re

from agent_service.learning_progress import current_step

LOCAL_INTENTS = {'continue', 'skip_check', 'followup', 'question', 'hint', 'example',
                 'greeting', 'thanks', 'social', 'self_report'}


def requested_action(decision, task, last):
    request = decision.learning_navigation
    step = current_step(task) if task else None
    if (not request or not step or request.step_id != step['id']
            or decision.target_task_id and decision.target_task_id != task['task_id']
            or task['context'].get('requires_mastery') or task['context'].get('memory_invalidated')
            or decision.relation == 'new_topic' or decision.proposed_actions or last.get('operation')
            or decision.requested_mode or decision.continuation_evidence or decision.comprehensive_check
            or decision.topic_closure or decision.clarification or decision.knowledge_card_status
            or decision.conversation_kind != 'ordinary' or decision.conversation_repair
            or decision.reply_feedback == 'response_only'
            or decision.programming_boundary != 'none' or decision.resource_boundary != 'none'
            or not set(decision.intents) <= LOCAL_INTENTS):
        return None
    text, evidence = last['content'], request.evidence
    start = text.find(evidence)
    if start < 0 or not evidence.strip():
        return None
    quoted = re.findall(r'https?://\S+|```[\s\S]*?```|“[^”]*”|‘[^’]*’|「[^」]*」|"[^"]*"|^>.*$', text, re.M)
    if any(evidence in span for span in quoted):
        return None
    if request.action == 'advance':
        clause = (re.split(r'[。！？!?;；，,\n]', text[:start])[-1] + evidence
                  + re.split(r'[。！？!?;；，,\n]', text[start + len(evidence):])[0])
        if re.search(r'(?:不要|先别|别|不用|不必|无需|不能|不想|不)\s*(?:再|先)?\s*'
                     r'(?:继续|进入|推进|往下|学习?下|到下|跳到|开始下)'
                     r'|(?:暂缓|暂停)\s*(?:继续|进入|推进)|don.t|not |unless|如果|除非', clause, re.I):
            return None
        prefix = re.split(r'[。！？!?;；\n]', text[:start])[-1]
        # A fronted condition may be separated from the governed action by a
        # comma. This is a negative fence, not positive keyword intent routing.
        if re.search(r'(?:不要|先别|别|不必|无需|不能|不用)\s*(?:在|等|当|因为|由于|如果|未|尚未)[^。！？!?;；\n]*[，,]\s*$', prefix):
            return None
    return request.action


def should_advance(decision, task, last):
    action = requested_action(decision, task, last)
    if decision.learning_navigation is not None:
        return action == 'advance' and bool(set(decision.intents) & {'continue', 'skip_check'})
    # Keep the existing explicit skip-check route. Bare continue is only a
    # topic relation until its same-call navigation reference is grounded.
    return 'skip_check' in decision.intents


def applied_to_run(run, task, decision, last, mode):
    applied = run.get('learning_navigation_applied') or {}
    step = current_step(task)
    return bool(applied and step and applied.get('input_ids') == run.get('input_ids')
        and applied.get('message_id') == last.get('message_id')
        and applied.get('mode') == mode and applied.get('task_id') == task['task_id']
        and applied.get('selected_step_id') == step['id']
        and applied.get('plan_version') == task['context']['learning_plan'].get('version')
        and applied.get('intents') == decision.intents
        and applied.get('request') == (decision.learning_navigation.model_dump() if decision.learning_navigation else None))


def record_selection(run, task, decision, last, mode, original_step_id):
    run['learning_navigation_applied'] = dict(input_ids=list(run['input_ids']),
        message_id=last['message_id'], mode=mode, task_id=task['task_id'],
        original_step_id=original_step_id, selected_step_id=current_step(task)['id'],
        plan_version=task['context']['learning_plan'].get('version'), intents=list(decision.intents),
        request=decision.learning_navigation.model_dump() if decision.learning_navigation else None)


def normalize(data, decision, last):
    task = data.get('tasks', {}).get(decision.target_task_id or data.get('active_task_id'))
    if (not task or not current_step(task) or task['context'].get('requires_mastery')
            or 'continue' not in decision.intents
            or not set(decision.intents) <= LOCAL_INTENTS - {'skip_check'}
            or decision.relation == 'new_topic' or last.get('operation') or decision.proposed_actions
            or decision.requested_mode or decision.continuation_evidence or decision.topic_closure
            or decision.clarification or decision.comprehensive_check):
        return decision
    run = data.get('runs', {}).get(last.get('run_id'), {})
    if should_advance(decision, task, last) or applied_to_run(run, task, decision, last, data.get('mode')):
        return decision
    # Missing/legacy or inconsistent navigation never starts a new lecture or
    # replaces the pending check. The current request is answered locally.
    intents = [item for item in decision.intents if item != 'continue']
    if not set(intents) & {'followup', 'hint', 'example'}:
        intents.append('followup')
    return decision.model_copy(update=dict(intents=intents, scope='continue_goal',
        target_task_id=task['task_id'], direct_teaching=False, answer_only=False, light_reply=''))
