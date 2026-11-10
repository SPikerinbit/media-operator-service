import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'motion/react'
import type { Lane } from './workbenchState'

export const asset=(name:string)=>`${import.meta.env.BASE_URL}workbench/${name}.webp`
export function Prop({name,layer='body',className='',style}: {name:string;layer?:string;className?:string;style?:React.CSSProperties}) {
  return <picture className={'prop '+className} style={style} aria-hidden="true">
    <source media="(prefers-color-scheme: dark)" srcSet={asset(`${name}-dark-${layer}`)}/>
    <img src={asset(`${name}-light-${layer}`)} alt="" draggable={false}/>
  </picture>
}

type Mark='clean'|'cut'|'charred'
const loaded=new Map<string,HTMLImageElement>()
function load(name:string) {
  if(loaded.has(name))return Promise.resolve(loaded.get(name)!)
  return new Promise<HTMLImageElement>((resolve,reject)=>{const img=new Image();img.onload=()=>{loaded.set(name,img);resolve(img)};img.onerror=reject;img.src=asset(name)})
}
function noise(x:number,seed:number){return Math.sin(x*.079+seed)*2.8+Math.sin(x*.213+seed*3)*1.3+Math.sin(x*.51+seed)*.6}

function paperSurface(title:string,mark:Mark) {
  const paper=document.createElement('canvas');paper.width=380;paper.height=450
  const c=paper.getContext('2d')!;c.fillStyle='#f9f7ec';c.fillRect(0,0,380,450)
  let seed=482; const random=()=>{seed=(seed*16807)%2147483647;return seed/2147483647}
  for(let i=0;i<9000;i++){c.fillStyle=`rgba(99,85,57,${random()*.038})`;c.fillRect(random()*380,random()*450,1,1)}
  c.fillStyle='#465054';c.font='18px "Source Han Sans CN", sans-serif';c.fillText(title.slice(0,18),24,43,330)
  c.fillStyle='#b6b9b4'
  for(let y=76;y<430;y+=28){c.fillRect(24,y,250+random()*70,1);c.fillStyle=y%3?'#c4c5bc':'#afb5b0'}
  if(mark==='charred'){
    c.save();c.beginPath();c.moveTo(278,0);for(let x=278;x<381;x+=3)c.lineTo(x,(x-278)*.75+noise(x,6));c.lineTo(380,0);c.closePath()
    c.strokeStyle='#704630';c.lineWidth=20;c.stroke();c.strokeStyle='#241a16';c.lineWidth=8;c.stroke();c.globalCompositeOperation='destination-out';c.fill();c.restore()
  }
  if(mark==='cut'){
    c.save();c.globalCompositeOperation='destination-out'
    for(let x=22;x<380;x+=29)c.fillRect(x,260+noise(x,4)*5,2.3,210)
    c.restore()
  }
  return paper
}

/** The paper mask is driven only by real progress. Flicker never advances the boundary. */
export function PaperProcess({lane,progress,status,title,mark='clean',active=true}: {
  lane:Lane;progress:number;status:string;title:string;mark?:Mark;active?:boolean
}) {
  const canvas=useRef<HTMLCanvasElement>(null)
  const previous=useRef(status)
  const smokeUntil=useRef(0)
  const reduced=useReducedMotion()
  const [textures,setTextures]=useState<{flame?:HTMLImageElement;smoke?:HTMLImageElement}>({})
  useEffect(()=>{let alive=true;if(lane==='publish')void Promise.all([load('flame-atlas'),load('smoke-atlas')]).then(([flame,smoke])=>{if(alive)setTextures({flame,smoke})}).catch(()=>{});return()=>{alive=false}},[lane])
  useEffect(()=>{
    if(status==='succeeded'&&previous.current!=='succeeded'&&active)smokeUntil.current=performance.now()+1100
    previous.current=status
  },[status,active])
  useEffect(()=>{
    const node=canvas.current;if(!node)return
    const c=node.getContext('2d')!;const dpr=Math.min(devicePixelRatio||1,2)
    node.width=520*dpr;node.height=350*dpr;c.scale(dpr,dpr)
    const paper=paperSurface(title,mark)
    let raf=0;let disposed=false;let last=0;let visible=!document.hidden
    const p=Math.min(1,Math.max(0,progress/100));let shown=p
    const start=performance.now()
    const running=status==='running'
    const draw=(now:number)=>{
      if(disposed)return
      if(now-last<1000/30 && running&&!reduced){raf=requestAnimationFrame(draw);return}last=now
      c.clearRect(0,0,520,350)
      shown=p
      const x=156,y=18,w=208,h=238
      if(lane==='publish'){
        const edge=y+h*(1-shown)
        if(shown<1){
          c.save();c.beginPath();c.moveTo(x,y);c.lineTo(x+w,y)
          for(let px=x+w;px>=x;px-=2)c.lineTo(px,Math.min(y+h,edge+noise(px,7)*1.7))
          c.closePath();c.clip();c.drawImage(paper,x,y,w,h)
          if(shown>0){
            c.beginPath();for(let px=x;px<=x+w;px+=2){const yy=edge+noise(px,7)*1.7;px===x?c.moveTo(px,yy):c.lineTo(px,yy)}
            c.strokeStyle='#a77042';c.lineWidth=17;c.stroke();c.strokeStyle='#34221c';c.lineWidth=8;c.stroke()
            if(running){c.strokeStyle='#ffba5b';c.lineWidth=1.5;c.stroke()}
          }c.restore()
        }
        if(running&&!reduced&&textures.flame){
          const frame=Math.floor(now/1000*24)%24
          c.save();c.globalCompositeOperation='screen';c.globalAlpha=.9
          c.drawImage(textures.flame,(frame%6)*512,Math.floor(frame/6)*256,512,256,x-34,edge-100,w+68,142);c.restore()
        }
        if(status==='succeeded'&&!reduced&&textures.smoke&&now<smokeUntil.current){
          const t=1-(smokeUntil.current-now)/1100;const frame=Math.min(23,Math.floor(t*24))
          c.save();c.globalAlpha=Math.sin(Math.PI*t)*.65
          c.drawImage(textures.smoke,(frame%6)*256,Math.floor(frame/6)*256,256,256,176,100-t*75,170,170);c.restore()
        }
      }else{
        const feed=196;const remaining=h*(1-shown)
        if(remaining>0){c.save();c.beginPath();c.rect(x,0,w,feed);c.clip();c.drawImage(paper,x,feed-remaining,w,h);c.restore()}
        if(shown>0){
          for(let i=0;i<12;i++){
            const sw=380/12;const length=Math.min(83,shown*h)+noise(i*21,4)*1.5
            c.save();c.translate(x+i*w/12,226);c.rotate((i-5.5)*.006)
            c.drawImage(paper,i*sw,Math.max(0,450*shown-150),sw-2,Math.min(150,450*shown),0,0,w/12-2,length);c.restore()
          }
        }
      }
      if(active&&visible&&!reduced&&(running||now<smokeUntil.current||now-start<200))raf=requestAnimationFrame(draw)
    }
    const visibility=()=>{visible=!document.hidden;cancelAnimationFrame(raf);if(visible)raf=requestAnimationFrame(draw)}
    document.addEventListener('visibilitychange',visibility);raf=requestAnimationFrame(draw)
    return()=>{disposed=true;cancelAnimationFrame(raf);document.removeEventListener('visibilitychange',visibility);paper.width=paper.height=0}
  },[lane,progress,status,title,mark,active,reduced,textures])
  return <div className={'paper-process '+lane} data-mark={mark}>
    <Prop name={lane==='publish'?'brazier':'shredder'} className="process-machine"/>
    <canvas ref={canvas} className="process-paper" aria-hidden="true"/>
    <Prop name={lane==='publish'?'brazier':'shredder'} layer="front" className="process-machine foreground"/>
  </div>
}

/** Twelve short paper bands bend into the envelope; content is a frozen submission snapshot. */
export function FoldingPaper({lines,folding}: {lines:string[];folding:boolean}) {
  return <div className={'folding-paper '+(folding?'folding':'')} aria-hidden="true">
    {Array.from({length:12},(_,i)=><div key={i} className="paper-band" style={{'--band':i} as React.CSSProperties}>
      <div className="paper-band-content" style={{top:-i*24}}>{lines.slice(0,6).map((line,n)=><span key={n}>{line.replace(/\s+/g,' ')}</span>)}</div>
    </div>)}
  </div>
}
