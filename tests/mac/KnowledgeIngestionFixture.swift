import Foundation

// Abstract fixture for persistence/visual verification; never an actual model response.
enum KnowledgeIngestionFixture {
    static func payload(_ ids: [UUID]) throws -> AgentAPI.ExtractPayload {
        let cards: [[String: Any]] = ids.enumerated().map { i, id in [
            "id": id.uuidString, "learning_goal": "区分检索与生成的职责",
            "knowledge_type": "concept", "theme": "入库验收", "content_language": "zh",
            "question_language": "zh", "answer_language": "zh", "evidence_excerpt": "检索找到相关资料，生成依据资料组织回答。",
            "evidence_locator": "隔离测试", "title": "检索与生成 \(i + 1)", "explanation": "隔离测试卡片，验证本地保存与打开，不写入日常知识库。",
            "scoring_spec": ["learning_goal": "区分职责", "must_cover": ["检索找资料", "生成组织回答"], "acceptable_paraphrases": [], "common_misconceptions": [], "evidence": "隔离测试", "order_rules": ""],
            "questions": [["variant_index": 0, "prompt_text": "检索与生成分别负责什么？"]]
        ] }
        return try JSONDecoder().decode(AgentAPI.ExtractPayload.self, from: JSONSerialization.data(withJSONObject: [
            "understood_as": "隔离验收", "theme": "入库验收", "attribution": "claim", "risk_flagged": false,
            "risk_reason": "", "knowledge": cards]))
    }
}
