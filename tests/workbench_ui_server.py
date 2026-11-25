"""Isolated visual fixture. All network/media/AI/upload work is simulated."""
import json
import os
import sys
from pathlib import Path
root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=True)
os.environ['MEDIA_DESKTOP_HOME']=str(root/'profile')
os.environ['MEDIA_DESKTOP_DATA']=str(root/'data')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import desktop
desktop.prepare()
from app import main as media,desktop_config as config,desktop_sources,desktop_jobs as jobs,desktop_bilibili,desktop_models,knowledge,workbench_inbox as inbox
from fastapi import Request
import threading
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

_MOCK_READY_MODELS: set[str] = set()
_orig_model_status = desktop_models.status
def _mock_model_status(data, name):
    info = _orig_model_status(data, name)
    if name in _MOCK_READY_MODELS:
        info['available'] = True
    return info
def _mock_model_prepare(data, name, proxy):
    if name not in desktop_models.MODELS:
        raise ValueError('不支持的 Whisper 模型')
    size = desktop_models.MODELS[name][1]
    with desktop_models.LOCK:
        if any(v.get('running') for v in desktop_models.PROGRESS.values()):
            return
        desktop_models.PROGRESS[name] = {
            'running': True, 'percent': 12, 'downloaded_bytes': int(size * 0.12),
            'total_bytes': size, 'failed': False, 'message': '正在后台下载 · 12%',
        }
    def _runner():
        for pct, msg in ((46, '正在后台下载 · 46%'), (88, '正在后台下载 · 88%'), (99, '正在校验模型完整性…')):
            time.sleep(0.55)
            with desktop_models.LOCK:
                desktop_models.PROGRESS[name].update(
                    running=True, percent=pct, downloaded_bytes=int(size * pct / 100),
                    total_bytes=size, failed=False, message=msg,
                )
        time.sleep(0.45)
        _MOCK_READY_MODELS.add(name)
        with desktop_models.LOCK:
            desktop_models.PROGRESS[name] = {
                'running': False, 'percent': 100, 'downloaded_bytes': size,
                'total_bytes': size, 'failed': False, 'message': '本地模型已准备好',
            }
    threading.Thread(target=_runner, daemon=True).start()
desktop_models.status = _mock_model_status
desktop_models.prepare = _mock_model_prepare
for route in app.routes:
    if getattr(route, 'path', '') == '/desktop/resources/check':
        def _fast_check():
            from app import desktop_routes
            return {
                **desktop_routes.resources(),
                'checks': [
                    {'label': 'FFmpeg / 字幕压制', 'ready': True},
                    {'label': 'NVIDIA / CUDA、cuDNN 和 GPU 推理', 'ready': False},
                    {'label': '资料目录写入', 'ready': True},
                ],
                'free_bytes': 120 * 10**9,
                'proxy': '',
            }
        route.dependant.call = _fast_check
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
    kinds=['judgment','fact','story','method','statement']
    with knowledge.database() as db:
        for index in range(values.get('count',3)):
            db.execute("INSERT OR IGNORE INTO card(transcript_id,topic,kind,mode,claim,evidence,example,refs,origin_key,quote_translation) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (values['transcript_id'],'框架',kinds[index%len(kinds)],'curated',f'测试观点 {index+1}','仅用于布局复验','','[1]',f'fixture-{index}',''))
    return {'ok':True}
@app.post('/fixture/summary-tree')
async def fixture_summary_tree(request:Request):
    from app import note_engine
    note_engine.initialize()
    values=await request.json()
    tid=values['transcript_id']
    run_id=f'fixture-summary-{tid}'
    with knowledge.database() as db:
        db.execute("INSERT OR REPLACE INTO note_run(id,transcript_id,mode,status,phase,version,updated,model,plan_json) VALUES(?,?,'summary','succeeded','done',?,?,?,?)",
                   (run_id,tid,note_engine.VERSION,time.time(),'fixture',json.dumps({
                       'total_tokens':18000,'leaf_count':4,'viewpoint_count':6,'summary_layers':2,'branching_factor':2,'top_count':2,'level_sizes':[4,2],'cost':0.75
                   },ensure_ascii=False)))
        leaves=[]
        for i in range(1,5):
            lid=db.execute("INSERT INTO note_node(run,key,level,position,cue,lo,hi,status,title,capsule,start_cue,end_cue,state_json) VALUES(?,?,0,?,1,0,10,'done',?,?,1,1,?)",
                           (run_id,f'leaf-{i}',i,f'小节 {i}：具体展开',json.dumps(f'第 {i} 节具体拆解与条件分析。',ensure_ascii=False),json.dumps({'title':f'小节 {i}：具体展开','summary':f'第 {i} 节具体拆解与条件分析。','role':'leaf'},ensure_ascii=False))).fetchone()
            lid=db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.execute('INSERT OR IGNORE INTO note_span VALUES(?,1,1,0,10)',(lid,))
            cid=db.execute("INSERT INTO note_candidate(run,node,topic,kind,claim,evidence,example,importance,specificity,identity) VALUES(?,?,?,?,?,?,?,3,3,?)",
                           (run_id,lid,'机制','story' if i%2 else 'judgment',f'底层具象观点 {i}：先记录再迭代','来自测试语段','历史卡片盒案例',f'cand-{tid}-{i}')).lastrowid
            db.execute('INSERT OR IGNORE INTO note_candidate_span VALUES(?,?,1)',(cid,lid))
            leaves.append(lid)
        branches=[]
        for b_idx,pair in enumerate([(leaves[0],leaves[1]),(leaves[2],leaves[3])],1):
            bid=db.execute("INSERT INTO note_node(run,key,level,position,status,title,capsule,start_cue,end_cue,state_json) VALUES(?,?,1,?,'done',?,?,1,1,?)",
                           (run_id,f'branch-{b_idx}',b_idx*2-1,f'主题 {b_idx}：核心脉络',json.dumps(f'主题 {b_idx} 聚合压缩概述。',ensure_ascii=False),json.dumps({'title':f'主题 {b_idx}：核心脉络','summary':f'主题 {b_idx} 聚合压缩概述。','role':'branch'},ensure_ascii=False))).lastrowid
            for child in pair: db.execute('INSERT OR IGNORE INTO note_edge VALUES(?,?)',(bid,child))
            branches.append(bid)
        root_id=db.execute("INSERT INTO note_node(run,key,level,position,status,title,capsule,start_cue,end_cue,state_json) VALUES(?,?,2,1,'done',?,?,1,1,?)",
                           (run_id,'overview','全篇主旨',json.dumps('全篇多层级压缩总览，先记录下来想法才有机会成为作品。',ensure_ascii=False),json.dumps({'title':'全篇主旨','summary':'全篇多层级压缩总览，先记录下来想法才有机会成为作品。','role':'overview'},ensure_ascii=False))).lastrowid
        for b in branches: db.execute('INSERT OR IGNORE INTO note_edge VALUES(?,?)',(root_id,b))
        db.execute('UPDATE note_run SET root=? WHERE id=?',(root_id,run_id))
        db.execute("INSERT OR REPLACE INTO note_active_mode(transcript_id,mode,run,updated) VALUES(?,'summary',?,?)",(tid,run_id,time.time()))
    return {'ok':True,'root_id':root_id}
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
