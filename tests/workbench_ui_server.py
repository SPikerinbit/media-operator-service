"""Isolated visual fixture. All network/media/AI/upload work is simulated."""
import os
import sys
from pathlib import Path
root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=True)
os.environ['MEDIA_DESKTOP_HOME']=str(root/'profile')
os.environ['MEDIA_DESKTOP_DATA']=str(root/'data')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import desktop
desktop.prepare()
from app import main as media,desktop_config as config,desktop_sources,desktop_jobs as jobs,desktop_bilibili,knowledge,workbench_inbox as inbox
from fastapi import Request
import uvicorn
import time

class Credentials:
    def get_password(self,service,name):return 'fixture' if name in {'TRANSLATE_API_KEY','BILI_SESSDATA','BILI_JCT','BILI_BUVID3'} else None
    def set_password(self,*args):pass
    def delete_password(self,*args):pass
config.VAULT=Credentials()
port=int(os.environ.get('MEDIA_UI_PORT','8801'))
app=desktop.application(f'http://127.0.0.1:{port}','workbench-review')
media.whisper_model_status=lambda *a:{'available':True}
media.bilibili_configured=lambda:True
desktop_bilibili.posting_zones=lambda:{201:'知识 / 科学'}
def probe(value,*args):
    if 'blocked' in value:raise desktop_sources.SourceError('session_required','请先在设置中登录小红书')
    return {'title':'如何把一个想法变成作品' if 'video' in value else '每天一条，记录思考的来路','media_type':'audio' if 'audio' in value else 'video',
            'platform':'来源视频','has_audio':True,'audio_direct':True,'duration':60}
desktop_sources.probe=probe
def run(stage):
    def execute(job_id):
        req=media.load_state(job_id).request
        result={}
        for p in (0,25,50,75,100):
            media.report_stage_progress(job_id,stage,p,'正在'+{'download':'获取素材','transcribe':'转录原文','translate':'翻译字幕','burn':'制作成片','bilibili_upload':'提交稿件'}[stage],force=True)
            time.sleep(.26)
        name='english.srt' if stage=='transcribe' else 'bilingual.srt' if stage=='translate' else 'video.mp4'
        target=media.artifact_path(job_id,name)
        target.write_text('1\n00:00:00,000 --> 00:00:03,000\n先记录下来，想法才有机会成为作品。\n',encoding='utf-8')
        if stage=='bilibili_upload':result={'bvid':'MOCK','bilibili_url':'https://www.bilibili.com/'}
        else:result={jobs.OUTPUTS[stage]:media.public_file_url(job_id,name)}
        if stage=='download':result.update(asset_type='audio' if req.get('audio_only') else 'video',has_audio=True,title='如何把一个想法变成作品')
        if stage=='translate':result['translated_srt_url']=result['bilingual_srt_url']
        media.report_stage_progress(job_id,stage,100,'已完成',status='succeeded',force=True,result=result)
    return execute
for stage in jobs.RUNNERS:jobs.RUNNERS[stage]=run(stage)
def generate(ident,*args,**kwargs):
    for p in (0,25,50,75,100):
        if kwargs.get('progress'):kwargs['progress'](p,'正在提取观点')
        time.sleep(.2)
    return 0
knowledge.generate_cards=generate
for route in app.routes:
    if getattr(route,'path','')=='/ui/preview-frame':
        async def preview(request:media.PreviewFrameRequest):return {'preview_image_url':'/static/desktop-ui/workbench/paper-light-beauty.webp'}
        route.dependant.call=preview
@app.post('/fixture/cards')
async def fixture_cards(request:Request):
    values=await request.json()
    with knowledge.database() as db:
        for index in range(values.get('count',3)):
            db.execute("INSERT OR IGNORE INTO card(transcript_id,claim,evidence,example,refs,origin_key,quote_translation) VALUES(?,?,?,?,?,?,?)",
                       (values['transcript_id'],f'测试观点 {index+1}','仅用于布局复验','','[1]',f'fixture-{index}',''))
    return {'ok':True}
@app.post('/fixture/long-notes')
async def long_notes(request:Request):
    values=await request.json()
    transcript=values['transcript_id']
    with knowledge.database() as db:
        db.executemany('INSERT OR REPLACE INTO cue VALUES(?,?,?,?,?)',[(transcript,i,i*2000,(i+1)*2000,'长原文段落 '+str(i)+'。'+('保持内容框内部滚动，机器位置不变。'*8)) for i in range(1,601)])
        db.execute("UPDATE card SET refs='[490]' WHERE transcript_id=?",(transcript,))
    return {'ok':True}

@app.post('/fixture/state')
async def fixture(request:Request):
    values=await request.json();entry=inbox.get_entry(values.pop('id'));inbox.update(entry['id'],**values);return {'ok':True}
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=port,access_log=False)
