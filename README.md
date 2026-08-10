# NovelWriter · 小说创作 Agent

一个本地运行的小说创作 MVP。每一本小说都有独立的章节、人物、时间线、设定事实、摘要与 AI 生成记录；后端在所有资源 API 中校验 `novel_id`，避免跨小说混用数据。

## 已实现功能

- 小说书架：创建、查看和管理多本小说。
- 三栏创作工作台：章节列表、长正文编辑、创作记忆与编审问题。
- 总纲与章节规划：总纲可手写；DeepSeek 可生成“待确认”的总纲/章节规划，再由用户确认创建章节。
- 大纲共创：输入自由文本改进要求后，AI 基于当前大纲、已确认主角、已确认剧情与正文事实生成预览；支持仅应用指定草稿章节、保留确认章节、版本快照和回退。
- 主要主角：人物可标为主要主角，记录当前位置、当前目标、情绪状态与成长弧线；已确认主角会以最高优先级带入大纲、写作与校验上下文。
- 流式正文：DeepSeek 的正文增量会直接显示在编辑器中，随后由用户保存或确认。
- 结构化记忆：确认章节时生成摘要、事件与事实草稿；仅确认的人物、时间线与事实会作为后续创作的强约束。
- 校验 Agent：检查时间线、人物/地点/关系、设定及大纲偏离，只返回问题和建议，不改写正文。
- 安全删除：书架可删除小说；章节列表和编辑器可删除章节。两者均有确认提示，章节删除会清理直接关联数据并重排后续章节。
- 后端 AI Provider 独立封装，DeepSeek 密钥只由后端 `.env` 读取。

## 启动

需要 Python 3.10+ 和 Node.js 20+。

1. 配置后端环境变量：

   ```bash
   cd /Users/gaoduan/Desktop/novelwriter/backend
   cp .env.example .env
   ```

   编辑 `.env`，填入你的 `DEEPSEEK_API_KEY`。未填密钥时，书架、编辑和本地数据库功能仍可使用；AI 功能会给出清晰错误提示。

2. 启动后端：

   ```bash
   cd /Users/gaoduan/Desktop/novelwriter/backend
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000
   ```

3. 在另一个终端启动前端：

   ```bash
   cd /Users/gaoduan/Desktop/novelwriter/frontend
   npm install
   npm run dev
   ```

   然后访问 <http://localhost:5173>。

默认使用 `sqlite:///./novelwriter.db`。要迁移到 PostgreSQL，只需把 `DATABASE_URL` 改成类似：

```env
DATABASE_URL=postgresql+psycopg://user:password@localhost/novelwriter
```

并安装 PostgreSQL 驱动，例如 `pip install psycopg[binary]`。

## 使用流程

1. 在书架创建小说，补充题材、主旨、目标字数与文风。
2. 在“大纲”页手写总纲，或点击“AI 生成大纲”。AI 返回的规划可编辑，确认后才会创建章节。
   - 已有总纲后，在“基于当前大纲继续改进”中填写反馈。先预览 `change_summary`、警告和逐章变更，再选择性应用；已确认章节默认跳过。
   - “查看版本快照”可恢复此前保存或 AI 应用前的总纲。
3. 在右侧“主要主角”中添加并完善主角资料。标记且确认后的主角设定会优先约束 AI。
4. 新建章节，填写章节大纲；若为空，点击“AI 建议章节大纲”，或输入反馈后使用“AI 改进本章大纲”。
5. 点击“生成章节”查看流式草稿；保存修改后的正文。
6. 点击“确认章节”，系统会提取摘要、时间线与事实草稿。通过 API 可编辑、确认或忽略这些条目。
7. 点击“校验章节”查看结构化矛盾提示和修改建议。

## API 概览

- `/api/novels`：小说的增删改查。
- `/api/novels/{novel_id}/chapters`：章节编辑、确认与删除。
- `/api/novels/{novel_id}/characters`、`/timeline`、`/facts`、`/outline`：结构化设定管理。
- `/api/novels/{novel_id}/ai/outline`、`/ai/plan-chapters`：仅返回可编辑 AI 提案；`/ai/apply-plan` 才持久化章节。
- `/api/novels/{novel_id}/ai/improve-outline`：返回大纲改进预览；`/ai/apply-outline-improvement` 选择性应用，确认章节自动跳过。
- `/api/novels/{novel_id}/outline-revisions`：大纲快照与恢复。
- `/api/novels/{novel_id}/chapters/{chapter_id}/ai/generate`：SSE 流式正文。
- `/api/novels/{novel_id}/chapters/{chapter_id}/ai/validate`：结构化编审结果。

交互式 API 文档：<http://localhost:8000/docs>。
