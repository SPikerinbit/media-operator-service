"""Isolated desktop fixture server. Never reads the user's credentials or settings.

Run with a disposable absolute directory and serve only on loopback. All outbound
AI/posting calls are replaced; real media work is covered by the separate smoke test.
"""
import json
import os
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=True)
os.environ.update(MEDIA_DESKTOP_HOME=str(root / "profile"), MEDIA_DESKTOP_DATA=str(root / "data"),
                  MEDIA_DESKTOP_TOOLS=r"D:\Media Operator\tools", MEDIA_DESKTOP_FONTS=r"D:\Media Operator\fonts")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import desktop
desktop.prepare()
from app import desktop_config as config, knowledge, desktop_jobs, desktop_bilibili
from app import main as media
import uvicorn


class TestCredentials:
    values = {"TRANSLATE_API_KEY": "fixture-key", "BILI_SESSDATA": "fixture", "BILI_JCT": "fixture", "BILI_BUVID3": "fixture"}
    def get_password(self, service, name):
        return self.values.get(name)
    def set_password(self, service, name, value):
        self.values[name] = value
    def delete_password(self, service, name):
        self.values.pop(name, None)


config.VAULT = TestCredentials()
vault = root / "Obsidian 验证库"
(vault / ".obsidian").mkdir(parents=True, exist_ok=True)
config.update({"data_dir": str(root / "data"), "obsidian_vault": str(vault), "ai_model": "mock-model"}, {})
app = desktop.application("http://127.0.0.1:8799", "studio-review")
sentences = [
    ("Make a prediction before you read the answer.", "看答案之前，先作出自己的预测。", "先预测，再核对"),
    ("A useful note tells your future self when to use an idea.", "一条有用的笔记，会告诉未来的你在什么情况下使用这个想法。", "为未来的使用写笔记"),
    ("If you cannot name the assumption, you cannot test it.", "如果你说不出假设是什么，就无法检验它。", "让假设可以被检验"),
    ("The point of a first draft is to discover what you think.", "初稿的作用，是发现自己究竟在想什么。", "用初稿厘清想法"),
]
if not knowledge.list_transcripts():
    for index in range(200):
        count = 3000 if index == 0 else 3
        file = root / ("How to remember what you learn.srt" if index == 0 else f"阅读笔记与思考方法 {index:03d}.srt")
        file.write_text("\n\n".join(
            f"{n+1}\n{knowledge.clock(n*2000).replace('.', ',')} --> {knowledge.clock((n+1)*2000).replace('.', ',')}\n{sentences[n%4][0]}"
            for n in range(count)), encoding="utf-8")
        ident = knowledge.register(file, source_kind="subtitle", source=str(file), title=file.name)
        if index == 0:
            with knowledge.database() as db:
                db.executemany("""INSERT INTO card(transcript_id,claim,evidence,example,quote_translation,refs,origin_key)
                               VALUES(?,?,?,?,?,?,?)""", [
                    (ident, sentences[n%4][2], "", "", sentences[n%4][1], json.dumps([n*29+1]), f"fixture-{n}") for n in range(100)
                ])

media.load_youtube_preview_metadata = lambda url: {"title": "来源视频 · " + url.rsplit("/",1)[-1], "description": "原简介"}
desktop_bilibili.posting_zones = lambda: {201: "知识 / 科学", 202: "知识 / 人文"}
knowledge.generate_cards = lambda *args, **kwargs: 0

if not list(media.BATCHES_DIR.glob("*.json")):
    batch = media.create_batch(media.BatchCreateRequest(rights_confirmed=True, subtitle_output_mode="en_only", sources=[
        {"source_kind": "local", "source_value": str(root / f"阅读与复习方法 {index+1}.mp4"),
         "source_title": f"阅读与复习方法 {index+1}"} for index in range(3)
    ]))
    for index, item in enumerate(batch.items):
        media.update_batch_item(batch.batch_id, item.item_id, status="failed" if index == 1 else "succeeded",
                                stage="transcribe" if index == 1 else "done", progress=30 if index == 1 else 100,
                                message="本地模型尚未准备好" if index == 1 else "已完成",
                                error={"message": "请在设置中下载模型后重试。"} if index == 1 else None)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8799, access_log=False)
