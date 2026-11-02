'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const escapeHTML = s => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const now = Date.now()/1000;
const examples = [
 ['m01','蓝桥 · 一次深夜加班','在蓝桥公司加班的那天，我们沿着河边走了很久，聊起正在做的项目。',['蓝桥','加班','项目'],8,.96],
 ['m02','蓝桥 · 十一点的约定','那次在蓝桥，约好以后晚上十一点就休息，给明天留一点精神。',['蓝桥','约定','休息'],9,.98],
 ['m03','海边 · 日出之前','一起去海边等日出。天还没亮，风有些凉，远处的灯塔一直亮着。',['海边','日出','灯塔'],9,.94],
 ['m04','灯塔 · 一张明信片','后来收到一张灯塔明信片，背面写着：下次还去看海。',['灯塔','海边','明信片'],7,.87],
 ['m05','咖啡 · 雨天的小店','下雨那天躲进街角的小店，点了一杯热咖啡，听雨敲在玻璃上。',['咖啡','雨天','小店'],6,.82],
 ['m06','小店 · 靠窗的座位','那家小店靠窗的位置很安静，适合慢慢写东西。',['小店','写作','安静'],6,.76],
 ['m07','余忆 · 第一个原型','完成余忆的第一个记忆原型：把经历写进账本，让重要的事留下来。',['余忆','项目','记忆'],9,.99],
 ['m08','记忆 · 想起的路径','讨论了关键词之间的关联，希望每一次想起，都能解释它从哪里来。',['记忆','关联','项目'],8,.93],
 ['m09','散步 · 橙色的晚霞','傍晚出门散步，看见整片橙色的晚霞，像城市上方缓慢燃烧的海。',['散步','晚霞','城市'],7,.88],
 ['m10','城市 · 一场电影','周末在城市另一头看了一场科幻电影，出来后聊起宇宙和未来。',['城市','电影','科幻'],7,.84],
 ['m11','科幻 · 星空手稿','画了一张科幻星空的手稿，想把记忆做成会发光的神经元。',['科幻','星空','记忆'],8,.96],
 ['m12','写作 · 留给未来','写下一段给未来的文字：细节可以淡去，重要的温度要留下。',['写作','记忆','未来'],8,.91],
];
function seed(){return examples.map((a,i)=>({id:a[0],title:a[1],text:a[2],keywords:a[3],anchors:a[3],importance:a[4],retention:a[5],stage:'vivid',kind:i===1?'promise':'event',status:i===1?'open':'recorded',created:now-(i+1)*86400,source_role:'demo',sources:[],suppressed:false}));}
let memories,apiMode=false,selectedId='m02',view='network',active=new Map(),activePaths=[],recallEpoch=0,rotation=true,zoom=1,yaw=-.2,pitch=.06,cinematic=false;
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
if(reduced)rotation=false;
try{const saved=JSON.parse(localStorage.getItem('yuyi-neural-v1'));memories=saved?normalize(saved):seed();}catch{memories=seed();}
function normalize(data){
 const rows=Array.isArray(data)?data:(data.memories||data.episodes);
 if(!Array.isArray(rows)||rows.length>1000)throw Error('账本必须是最多 1000 条记录的数组');
 const ids=new Set();
 return rows.map((m,i)=>{
  if(!m||typeof m!=='object')throw Error('记忆格式无效');
  const text=m.text||m.gist||m.impression;
  if(typeof text!=='string'||!text.trim()||text.length>5000)throw Error('每条记忆需要有效正文（最多 5000 字）');
  const id=String(m.id||'import_'+i);
  if(id.length>100||ids.has(id))throw Error('记忆编号重复或过长');ids.add(id);
  const keywords=[...(Array.isArray(m.keywords)?m.keywords:[]),...(Array.isArray(m.anchors)?m.anchors:[])].filter(x=>typeof x==='string'&&x.trim().length>=2&&x.length<=40);
  return {id,title:typeof m.title==='string'?m.title.slice(0,70):text.slice(0,20),text,keywords:[...new Set(keywords)].slice(0,32),anchors:[],importance:Number.isFinite(m.importance)?Math.max(3,Math.min(10,m.importance)):7,retention:Number.isFinite(m.retention)?Math.max(0,Math.min(1,m.retention)):.9,stage:['vivid','faded','impression'].includes(m.stage)?m.stage:'vivid',kind:m.kind||'event',status:m.status||'recorded',created:Number.isFinite(m.created)?m.created:now,suppressed:!!m.suppressed,corrected:!!m.corrected,source_role:m.source_role||'imported',sources:Array.isArray(m.sources)?m.sources:[]};
 });
}
let toastTimer;
function toast(text){$('#toast').textContent=text;$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),3500);}
function save(){if(!apiMode)try{localStorage.setItem('yuyi-neural-v1',JSON.stringify(memories));}catch{toast('浏览器存储不可用，请导出账本保存');}}
async function api(path,body,method='POST'){
 const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
 const d=await r.json();if(!r.ok)throw Error(d.error||'本地服务请求失败');return d;
}
async function initialize(){
 if(location.protocol.startsWith('http')){
  try{const r=await fetch('/api/state',{signal:AbortSignal.timeout(1800)});if(r.ok&&(r.headers.get('content-type')||'').includes('application/json')){const d=await r.json();if(d.engine==='yuyi-python'){memories=normalize(d.memories);apiMode=true;$('#connectionLabel').textContent='Python 已连接';$('#storageLabel').textContent='SQLite 记忆账本';$('#sourceLabel').textContent='本地 Python 账本';$('#footerHint').textContent='LOCAL PYTHON ENGINE · SQLITE';$('#modeDescription').textContent='已连接配套 Python 本地服务。读取、写入、压制和删除由余忆真实模块执行；数据保存在命令行指定的目录。';}}}catch{}
 }
 if(!memories.some(m=>m.id===selectedId))selectedId=memories[0]?.id||'';
 rebuildGraph();renderInspector();renderLedger();renderStats();
}
function setView(name){view=name;$$('.view').forEach(el=>el.hidden=el.id!==name+'View');$$('.nav').forEach(el=>el.classList.toggle('active',el.dataset.view===name));if(name==='network')resize();if(name==='ledger')renderLedger();}
$$('.nav').forEach(el=>el.addEventListener('click',()=>setView(el.dataset.view)));
$('.brand').addEventListener('click',e=>{e.preventDefault();setView('network');});
function renderInspector(){
 const m=memories.find(x=>x.id===selectedId);
 if(!m){$('#selectedTitle').textContent='等待第一段记忆';$('#selectedText').textContent='写入一段经历，点亮第一个事件节点。';$('#selectedTags').replaceChildren();$('#selectedId').textContent='EMPTY';$('#retentionValue').innerHTML='0<small>%</small>';$('#retentionBar').style.width='0%';$('#importance').textContent='—';return;}
 $('#selectedTitle').textContent=m.title;
 $('#selectedText').textContent=m.text;
 $('#selectedId').textContent=m.id.length>15?m.id.slice(0,12).toUpperCase():'MEM_'+m.id.replace(/^m/,'').padStart(3,'0').toUpperCase();
 $('#selectedStage').textContent=m.suppressed?'已压制':m.corrected?'已更正':({vivid:'清晰记忆',faded:'模糊记忆',impression:'残留印象'}[m.stage]);
 $('#selectedTags').innerHTML=m.keywords.slice(0,6).map(t=>'<span>'+escapeHTML(t)+'</span>').join('');
 const r=Math.round(m.retention*100);$('#retentionValue').innerHTML=r+'<small>%</small>';$('#retentionBar').style.width=r+'%';
 $('#memoryKind').textContent=m.kind==='promise'?'承诺 / PROMISE':'事件 / EVENT';
 $('#importance').innerHTML='<span style="color:var(--amber);letter-spacing:2px">'+('▮'.repeat(m.importance))+ '</span> <span class="mono">'+m.importance+'/10</span>';
 $('#sourceLabel').textContent=apiMode?'本地 Python 账本':m.source_role==='demo'?'虚构演示数据':m.source_role==='trusted_caller'?'手动确认写入':'导入的账本记录';
 $('#suppressSelected').title=m.suppressed?'恢复当前记忆':'压制当前记忆';
}
function renderLedger(){
 $('#ledgerList').innerHTML=memories.length?memories.map(m=>`<article class="ledger-card ${m.suppressed?'suppressed':''}"><span class="mono">${escapeHTML(m.id.slice(0,14).toUpperCase())} / ${m.suppressed?'SUPPRESSED':m.corrected?'CORRECTED':escapeHTML(m.stage.toUpperCase())}</span><h3>${escapeHTML(m.title)}</h3><p>${escapeHTML(m.text)}</p><div class="tags">${m.keywords.slice(0,6).map(t=>'<span>'+escapeHTML(t)+'</span>').join('')}</div><div class="ledger-actions"><button data-select="${escapeHTML(m.id)}">查看神经节点 ↗</button><button data-suppress="${escapeHTML(m.id)}">${m.suppressed?'恢复':'压制'}</button><button class="delete" data-delete="${escapeHTML(m.id)}">删除</button></div></article>`).join(''):'<p class="muted">账本为空。写入一段记忆，开始构建你的网络。</p>';
}
$('#ledgerList').addEventListener('click',async e=>{
 const b=e.target.closest('button');if(!b)return;
 if(b.dataset.select){selectedId=b.dataset.select;renderInspector();setView('network');pulseAt(selectedId);}
 if(b.dataset.suppress)await suppress(b.dataset.suppress);
 if(b.dataset.delete){const m=memories.find(x=>x.id===b.dataset.delete);if(!m||!confirm('删除这段记忆？\n'+m.title+'\n此操作不可恢复，关联将在下一次读取时移除。'+(apiMode?'\nPython 模式还会清理包含相同正文的关联记录与聊天队列。':'')))return;
  try{if(apiMode){await api('/api/delete',{id:m.id});memories=normalize((await api('/api/state',null,'GET')).memories);}else memories=memories.filter(x=>x.id!==m.id);if(!memories.some(x=>x.id===selectedId))selectedId=memories[0]?.id||'';resetRecall();save();rebuildGraph();renderLedger();renderInspector();toast('记忆及其关联已移除');}catch(error){toast(error.message);}}
});
async function suppress(id){const m=memories.find(x=>x.id===id);if(!m)return;try{if(apiMode)await api('/api/suppress',{id,value:!m.suppressed});m.suppressed=!m.suppressed;resetRecall();save();rebuildGraph();renderInspector();renderLedger();toast(m.suppressed?'记忆已压制，不再参与召回':'记忆已恢复');}catch(error){toast(error.message);}}
$('#suppressSelected').addEventListener('click',()=>suppress(selectedId));
function bigrams(text){const s=text.toLowerCase().replace(/\s/g,'');return new Set(s.length<2?[s]:Array.from({length:s.length-1},(_,i)=>s.slice(i,i+2)));}
function browserRecall(query){
 const live=memories.filter(m=>!m.suppressed&&!m.corrected),q=bigrams(query),scores=new Map(),paths=new Map();
 for(const m of live){const bg=bigrams(m.text+' '+m.keywords.join(' '));let n=0;for(const x of q)if(bg.has(x))n++;const rel=n/Math.max(1,Math.min(q.size,bg.size));if(rel>=.12){scores.set(m.id,rel);paths.set(m.id,[{kind:'direct',event:m.id}]);}}
 let frontier=[...scores.keys()].sort((a,b)=>scores.get(b)-scores.get(a)).slice(0,20);
 for(let hop=0;hop<2;hop++){
  const next=new Set();
  for(const a of frontier){const ma=live.find(x=>x.id===a);for(const mb of live){if(a===mb.id)continue;const cue=ma.keywords.find(t=>mb.keywords.includes(t));if(!cue)continue;const count=live.filter(x=>x.keywords.includes(cue)).length;const age=Math.max(0,Date.now()/1000-Math.min(ma.created,mb.created));const value=scores.get(a)*.7*.65/Math.sqrt(Math.max(1,count-1))*2**(-age/(90*86400));if(value>=.12&&value>(scores.get(mb.id)||0)){scores.set(mb.id,value);paths.set(mb.id,[...paths.get(a),{kind:'shared_cue',cue,from:a,event:mb.id}]);next.add(mb.id);}}}
  frontier=[...next].sort((a,b)=>scores.get(b)-scores.get(a)).slice(0,20);
 }
 return live.filter(m=>scores.has(m.id)).sort((a,b)=>(scores.get(b.id)+.4*b.retention+.03*b.importance)-(scores.get(a.id)+.4*a.retention+.03*a.importance)).slice(0,3).map(m=>({id:m.id,text:m.text,relevance:scores.get(m.id),path:paths.get(m.id)}));
}
function resetRecall(){active.clear();activePaths=[];$('#traceCount').textContent='WAITING FOR SIGNAL';$('#traceContent').innerHTML='<div class="trace-empty">⌁<p>输入一个线索<br><span>看看记忆如何被唤醒</span></p></div>';$('#fieldStatus').textContent='SYSTEM STANDBY';renderStats();}
let reading=false;
async function recall(query){
 query=query.trim();if(!query){toast('给记忆一个线索，比如「加班」');return;}if(reading)return;
 reading=true;$('#query').value=query;$('#recallButton').disabled=true;$('#fieldStatus').textContent='PROPAGATING SIGNAL';$('#fieldCaption').textContent='信号正在穿过记忆网络';$('#networkState').textContent='关联激活中';
 const start=performance.now();
 try{
  const rows=apiMode?(await api('/api/recall',{query})).results:browserRecall(query);
  active=new Map(rows.map(r=>[r.id,r]));activePaths=rows.map(r=>r.path);recallEpoch=performance.now();
  $('#traceCount').textContent=String(rows.length).padStart(2,'0')+' MEMORIES ACTIVATED';
  const route=rows.reduce((best,r)=>!best||r.path.length>best.path.length?r:best,null);
  const longest=route?.path||[];
  if(rows.length){selectedId=route.id;renderInspector();
   const lines=[{kind:'query',label:query,description:'输入线索 / INPUT SIGNAL'}];
   for(const step of longest){const m=memories.find(x=>x.id===step.event);if(step.kind==='shared_cue')lines.push({kind:'cue',label:step.cue,description:'共享线索 / ASSOCIATION'});lines.push({kind:step.kind,label:m?.title||step.event,description:step.kind==='direct'?'直接命中 / DIRECT MATCH':'关联激活 / SPREAD ACTIVATION'});}
   $('#traceContent').innerHTML=lines.map(l=>`<div class="trace-item ${l.kind==='cue'?'cue':''}"><i></i><div><b>${escapeHTML(l.label)}</b><p>${escapeHTML(l.description)}</p></div></div>`).join('');
   $('#fieldCaption').textContent=rows.length+' 段记忆已被唤醒';$('#fieldSubcaption').textContent='脉冲沿真实命中与共享线索传播';
  }else{$('#traceContent').innerHTML='<div class="trace-empty">∅<p>没有找到相关记忆<br><span>换一个线索试试</span></p></div>';$('#fieldCaption').textContent='没有相关记忆，不用旧事补位';$('#fieldSubcaption').textContent='试试「加班」「海边」「咖啡」';}
  $('#fieldStatus').textContent=rows.length?'RECALL SEQUENCE COMPLETE':'NO MATCHING SIGNAL';$('#networkState').textContent='读取完成 · 未触发巩固';renderStats();
 }catch(error){toast(error.message);$('#fieldStatus').textContent='RECALL INTERRUPTED';}
 finally{reading=false;$('#recallButton').disabled=false;}
}
$('#recallForm').addEventListener('submit',e=>{e.preventDefault();recall($('#query').value);});
$$('[data-query]').forEach(b=>b.addEventListener('click',()=>recall(b.dataset.query)));
$('#recallSelected').addEventListener('click',()=>{const m=memories.find(x=>x.id===selectedId);if(m)recall(m.keywords[0]||m.text.slice(0,8));});
function renderStats(){
 const live=memories.filter(m=>!m.suppressed&&!m.corrected);$('#nodeCount').textContent=String(live.length).padStart(2,'0');$('#linkCount').textContent=String(memoryLinks.length).padStart(2,'0');$('#statMemories').textContent=String(memories.length).padStart(2,'0');$('#statLinks').textContent=String(memoryLinks.length).padStart(2,'0');$('#statActive').textContent=String(active.size).padStart(2,'0');
}
function openWrite(){$('#writeDialog').showModal();setTimeout(()=>$('#newText').focus(),50);}
$('#writeTop').addEventListener('click',openWrite);$('#closeWrite').addEventListener('click',()=>$('#writeDialog').close());
$('#newImportance').addEventListener('input',()=>$('#importancePreview').textContent=$('#newImportance').value+' / 10');
$('#writeForm').addEventListener('submit',async e=>{
 e.preventDefault();const text=$('#newText').value.trim();if(!text)return;
 const keywords=[...new Set($('#newTags').value.split(/[,，、;；\n]/).map(s=>s.trim()).filter(s=>s.length>=2&&s.length<=40))].slice(0,12);
 const importance=Number($('#newImportance').value),button=$('#writeForm button[type=submit]');button.disabled=true;
 try{let m;if(apiMode){const d=await api('/api/remember',{text,keywords,importance});const state=await api('/api/state',null,'GET');memories=normalize(state.memories);m=memories.find(x=>x.id===d.id);}else{m={id:'m_'+crypto.randomUUID().slice(0,8),title:text.slice(0,20),text,keywords,anchors:[],importance,retention:1,stage:'vivid',kind:'event',status:'recorded',created:Date.now()/1000,source_role:'trusted_caller',sources:[],suppressed:false};memories.push(m);}
  selectedId=m?.id||memories.at(-1)?.id;save();rebuildGraph();renderInspector();renderLedger();$('#writeDialog').close();$('#writeForm').reset();$('#importancePreview').textContent='8 / 10';$('#writeError').textContent='';setView('network');pulseAt(selectedId);toast('编码完成 · 新记忆已进入账本');
 }catch(error){$('#writeError').textContent=error.message;}finally{button.disabled=false;}
});
$('#exportButton').addEventListener('click',()=>{const blob=new Blob([JSON.stringify({schema:'yuyi-neural-1',exported_at:new Date().toISOString(),memories},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='yuyi-memory-ledger.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('账本已导出');});
$('#importButton').addEventListener('click',()=>{if(apiMode){toast('Python 模式请通过后端管理账本；浏览器导入不会覆盖 SQLite');return;}$('#importFile').click();});
$('#importFile').addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>5000000)throw Error('文件不能超过 5 MB');const rows=normalize(JSON.parse(await file.text()));if(!confirm('将当前浏览器账本替换为导入的 '+rows.length+' 条记忆？建议先导出备份。'))return;memories=rows;selectedId=rows[0]?.id||'';resetRecall();save();rebuildGraph();renderInspector();renderLedger();toast('账本已导入，神经网络已重建');}catch(error){toast('导入失败：'+error.message);}finally{e.target.value='';}});
$('#helpButton').addEventListener('click',()=>$('#helpDialog').showModal());$('#closeHelp').addEventListener('click',()=>$('#helpDialog').close());
$('#fullscreen').addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch{toggleCinema();toast('当前窗口不支持全屏，已切换沉浸模式');}});
function toggleCinema(){cinematic=!cinematic;document.body.classList.toggle('cinematic',cinematic);resize();if(cinematic)toast('沉浸展示已开启 · 按 Esc 退出');}
$('#cinema').addEventListener('click',toggleCinema);
$('#rotate').addEventListener('click',()=>{rotation=!rotation;$('#rotate').classList.toggle('selected',rotation);});
$('#resetCamera').addEventListener('click',()=>{yaw=-.2;pitch=.06;zoom=1;toast('视角已复位');});
document.addEventListener('keydown',e=>{const editing=['INPUT','TEXTAREA'].includes(document.activeElement?.tagName);if(e.key==='/'&&!editing&&!$('dialog[open]')){e.preventDefault();setView('network');$('#query').focus();}if(e.key==='Escape'&&cinematic){cinematic=false;document.body.classList.remove('cinematic');resize();}});

// Art-directed 3D connectome. Background neurons are ornamental; event IDs are real.
const canvas=$('#neuralCanvas'),ctx=canvas.getContext('2d');
let width=800,height=490,dpr=1,decor=[],eventNodes=[],cueNodes=[],memoryLinks=[],projected=[],stars=[];
let randomState=75439;
function random(){randomState=(randomState*16807)%2147483647;return(randomState-1)/2147483646;}
function spherePoint(i,total,side){const u=1-2*(i+.5)/total,a=i*2.39996323,r=Math.sqrt(1-u*u);return{x:side*(.16+.54*r*Math.abs(Math.cos(a))),y:u*.86,z:r*Math.sin(a)*.59};}
for(let side of [-1,1])for(let i=0;i<92;i++){const p=spherePoint(i,92,side);decor.push({...p,phase:random()*6.28,r:random()*1.4+.4,branches:Array.from({length:3+Math.floor(random()*3)},()=>({a:random()*6.28,len:.035+random()*.085}))});}
for(let i=0;i<95;i++)stars.push({x:random(),y:random(),r:random()*.7+.2,phase:random()*6.28});
const decorativeLinks=[];
for(let i=0;i<decor.length;i++){const d=decor[i];const nearest=decor.map((b,j)=>({j,d:(d.x-b.x)**2+(d.y-b.y)**2+(d.z-b.z)**2})).filter(x=>x.j!==i&&x.d<.13).sort((a,b)=>a.d-b.d).slice(0,3);for(const n of nearest)if(n.j>i)decorativeLinks.push([i,n.j]);}
function rebuildGraph(){
 const live=memories.filter(m=>!m.suppressed&&!m.corrected);
 eventNodes=live.map((m,i)=>{const k=(i*13+19)%decor.length,p=decor[k];return {...p,x:p.x*1.08,y:p.y*.87,z:p.z*1.1,id:m.id,title:m.title,type:'event',index:i};});
 const cues=new Map();for(const m of live)for(const s of m.keywords){if(!cues.has(s))cues.set(s,[]);cues.get(s).push(m.id);}
 cueNodes=[];memoryLinks=[];
 for(const [cue,ids]of cues){if(ids.length<2)continue;const nodes=ids.map(id=>eventNodes.find(n=>n.id===id));const p=nodes.reduce((s,n)=>({x:s.x+n.x/nodes.length,y:s.y+n.y/nodes.length,z:s.z+n.z/nodes.length}),{x:0,y:0,z:0});const n={...p,x:p.x*1.18,y:p.y*1.13,z:p.z+.1,id:'cue:'+cue,title:cue,type:'cue'};cueNodes.push(n);for(const id of ids)memoryLinks.push({a:id,b:n.id,cue});}
 renderStats();
}
function resize(){const r=$('#fieldWrap').getBoundingClientRect();if(!r.width||!r.height)return;width=r.width;height=r.height;dpr=Math.min(devicePixelRatio||1,2);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);}
new ResizeObserver(resize).observe($('#fieldWrap'));
function project(p){const c=Math.cos(yaw),s=Math.sin(yaw),x=p.x*c+p.z*s,z=-p.x*s+p.z*c,cy=Math.cos(pitch),sy=Math.sin(pitch),y=p.y*cy-z*sy,zz=p.y*sy+z*cy;const perspective=3.5/(3.5+zz),scale=Math.min(width*.40,height*.435)*zoom;return{x:width*.49+x*scale*perspective,y:height*.46+y*scale*perspective,z:zz,k:perspective,scale};}
function curve(a,b,bend=.07){ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.quadraticCurveTo((a.x+b.x)/2+(b.y-a.y)*bend,(a.y+b.y)/2-(b.x-a.x)*bend,b.x,b.y);ctx.stroke();}
function glow(x,y,r,color,alpha=1){const g=ctx.createRadialGradient(x,y,0,x,y,r);g.addColorStop(0,color+Math.round(alpha*160).toString(16).padStart(2,'0'));g.addColorStop(.2,color+'40');g.addColorStop(1,color+'00');ctx.fillStyle=g;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();}
let last=performance.now(),pulseId='',pulseTime=0;
function pulseAt(id){pulseId=id;pulseTime=performance.now();}
function draw(time){
 requestAnimationFrame(draw);if(view!=='network'||document.hidden)return;const dt=Math.min(time-last,50);last=time;if(rotation&&!reduced)yaw+=dt*.000035;
 ctx.clearRect(0,0,width,height);
 const cx=width*.49,cy=height*.46,scale=Math.min(width*.4,height*.435)*zoom;
 // Subtle spatial graticule and suspended projection cradle.
 ctx.lineWidth=.5;
 for(let i=0;i<stars.length;i++){const p=stars[i];ctx.fillStyle=`rgba(112,174,179,${.1+Math.sin(time*.0004+p.phase)*.06})`;ctx.beginPath();ctx.arc(p.x*width,p.y*height,p.r,0,7);ctx.fill();}
 ctx.strokeStyle='#45616b10';ctx.setLineDash([2,7]);ctx.beginPath();ctx.moveTo(cx,45);ctx.lineTo(cx,height-55);ctx.moveTo(40,cy);ctx.lineTo(width-40,cy);ctx.stroke();ctx.setLineDash([]);
 const baseY=cy+scale*.97;
 for(let i=0;i<3;i++){ctx.strokeStyle=i===0?'#619c9433':'#619c9414';ctx.lineWidth=i===0?.8:.5;ctx.beginPath();ctx.ellipse(cx,baseY,scale*(.96+i*.13),scale*(.17+i*.025),0,0,Math.PI*2);ctx.stroke();}
 ctx.setLineDash([3,11]);ctx.strokeStyle='#84dbc33a';ctx.beginPath();ctx.ellipse(cx,baseY,scale*1.03,scale*.185,0,time*.00007,time*.00007+4.4);ctx.stroke();ctx.setLineDash([]);
 ctx.strokeStyle='#85ead31a';for(let i=-3;i<=3;i++){ctx.beginPath();ctx.moveTo(cx+i*scale*.22,baseY+scale*.14);ctx.lineTo(cx+i*scale*.3,baseY+scale*.32);ctx.stroke();}
 // Central volume illumination.
 const halo=ctx.createRadialGradient(cx,cy,scale*.07,cx,cy,scale*1.15);halo.addColorStop(0,'#5bbca612');halo.addColorStop(.6,'#2d8b7b08');halo.addColorStop(1,'#246e6800');ctx.fillStyle=halo;ctx.fillRect(cx-scale*1.2,cy-scale*1.2,scale*2.4,scale*2.4);
 const dp=decor.map(project);
 for(const [a,b]of decorativeLinks){const depth=(dp[a].z+dp[b].z)/2,alpha=(.09+(1-depth)*.055)*(active.size?.55:1);ctx.strokeStyle=`rgba(96,193,176,${alpha})`;ctx.lineWidth=.55;curve(dp[a],dp[b],.15);}
 // Dendritic branching gives neurons organic rather than polygonal silhouettes.
 for(let i=0;i<decor.length;i++){const p=dp[i],n=decor[i],alpha=.14+(1-p.z)*.10;ctx.lineWidth=.5;ctx.strokeStyle=`rgba(115,209,188,${alpha})`;for(const b of n.branches){const angle=b.a+yaw*.15,len=b.len*scale*p.k;const ex=p.x+Math.cos(angle)*len,ey=p.y+Math.sin(angle)*len;ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.quadraticCurveTo(p.x+Math.cos(angle+.3)*len*.5,p.y+Math.sin(angle+.3)*len*.5,ex,ey);ctx.moveTo(ex,ey);ctx.lineTo(ex+Math.cos(angle+.8)*len*.35,ey+Math.sin(angle+.8)*len*.35);ctx.moveTo(ex,ey);ctx.lineTo(ex+Math.cos(angle-.6)*len*.29,ey+Math.sin(angle-.6)*len*.29);ctx.stroke();}ctx.fillStyle=`rgba(139,237,209,${alpha+.1})`;ctx.beginPath();ctx.arc(p.x,p.y,n.r*p.k,0,7);ctx.fill();if(i%11===0)glow(p.x,p.y,7,'#7be4c4',.23);}
 const all=[...eventNodes,...cueNodes];projected=all.map(n=>({...project(n),node:n}));const map=new Map(projected.map(p=>[p.node.id,p]));
 const activeEdges=new Set();for(const path of activePaths)for(const step of path){if(step.from){activeEdges.add(step.from+'|cue:'+step.cue);activeEdges.add(step.event+'|cue:'+step.cue);}}
 for(const edge of memoryLinks){const a=map.get(edge.a),b=map.get(edge.b);if(!a||!b)continue;const isActive=activeEdges.has(edge.a+'|'+edge.b),nearSelected=edge.a===selectedId;ctx.strokeStyle=isActive?'#a9f8e2b0':nearSelected?'#b2d9c85a':'#77b9ae28';ctx.lineWidth=isActive?1.2:.7;curve(a,b,.08);
  if(isActive&&!reduced){const f=((time-recallEpoch)*.00032+edge.a.length*.06)%1,from=active.get(edge.a)?.path.length===1?a:b,to=from===a?b:a;const x=from.x+(to.x-from.x)*f,y=from.y+(to.y-from.y)*f;glow(x,y,9,'#b7ffe6',.8);ctx.fillStyle='#d4fff0';ctx.beginPath();ctx.arc(x,y,1.5,0,7);ctx.fill();}
 }
 // Explicit user-evidence links may connect events without a shared keyword.
 for(const path of activePaths)for(const step of path){if(step.kind!=='evidence_edge')continue;const a=map.get(step.from),b=map.get(step.event);if(!a||!b)continue;ctx.strokeStyle='#b5e8dba0';ctx.lineWidth=1.1;ctx.setLineDash([3,4]);curve(a,b,.08);ctx.setLineDash([]);if(!reduced){const f=((time-recallEpoch)*.00028)%1;glow(a.x+(b.x-a.x)*f,a.y+(b.y-a.y)*f,10,'#b7ffe6',.8);}}
 for(const p of [...projected].sort((a,b)=>b.z-a.z)){const n=p.node,selected=n.id===selectedId,isActive=active.has(n.id),cueActive=n.type==='cue'&&[...activeEdges].some(s=>s.endsWith('|'+n.id)),isCue=n.type==='cue',color=isCue?'#e9b985':'#85ead3',r=(isCue?2.1:selected?4.3:3)*p.k;
  glow(p.x,p.y,(selected||isActive||cueActive?25:12)*p.k,color,selected||isActive?.8:.35);ctx.fillStyle=selected||isActive?'#e5fff6':color;ctx.beginPath();ctx.arc(p.x,p.y,r,0,7);ctx.fill();
  if(selected||isActive){ctx.strokeStyle=isActive?'#c3ffe881':'#85ead36a';ctx.lineWidth=.7;ctx.beginPath();ctx.arc(p.x,p.y,r+6,0,7);ctx.stroke();ctx.setLineDash([2,4]);ctx.strokeStyle='#85ead340';ctx.beginPath();ctx.arc(p.x,p.y,r+11,0,7);ctx.stroke();ctx.setLineDash([]);}
  if(n.id===pulseId&&time-pulseTime<2200){const f=(time-pulseTime)/2200;ctx.strokeStyle=`rgba(149,242,211,${1-f})`;ctx.beginPath();ctx.arc(p.x,p.y,9+f*65,0,7);ctx.stroke();}
  if((selected||isActive||isCue&&cueActive||!active.size&&n.index<3)&&width>450){const label=isCue?n.title:n.title.slice(0,14);ctx.font=`${isCue?9:10}px "Noto Sans SC","Microsoft YaHei",sans-serif`;const tx=p.x+14,ty=p.y-12,tw=ctx.measureText(label).width;ctx.fillStyle='#09151cbb';ctx.fillRect(tx-4,ty-12,tw+10,19);ctx.fillStyle=selected?'#d3f6e9':isCue?'#dbb78c':'#8bbab5';ctx.fillText(label,tx,ty+1);ctx.strokeStyle='#85ead33a';ctx.lineWidth=.6;ctx.beginPath();ctx.moveTo(p.x+5,p.y-3);ctx.lineTo(tx-4,ty+3);ctx.stroke();}
 }
 // Scientific viewfinder accents.
 ctx.strokeStyle='#8fb8b622';ctx.lineWidth=.7;const bx=cx-scale*.86,by=cy-scale*.94,bw=scale*1.72,bh=scale*1.88;for(const [x,y,sx,sy]of[[bx,by,1,1],[bx+bw,by,-1,1],[bx,by+bh,1,-1],[bx+bw,by+bh,-1,-1]]){ctx.beginPath();ctx.moveTo(x+sx*12,y);ctx.lineTo(x,y);ctx.lineTo(x,y+sy*12);ctx.stroke();}
}
let pointer=null,dragged=false,hoverId='';
canvas.addEventListener('pointerdown',e=>{pointer={x:e.clientX,y:e.clientY};dragged=false;canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointermove',e=>{
 const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;
 if(pointer){const dx=e.clientX-pointer.x,dy=e.clientY-pointer.y;if(Math.abs(dx)+Math.abs(dy)>2)dragged=true;yaw+=dx*.006;pitch=Math.max(-.65,Math.min(.65,pitch+dy*.005));pointer={x:e.clientX,y:e.clientY};$('#tooltip').hidden=true;return;}
 const p=projected.filter(p=>p.node.type==='event').sort((a,b)=>Math.hypot(a.x-x,a.y-y)-Math.hypot(b.x-x,b.y-y))[0];
 if(p&&Math.hypot(p.x-x,p.y-y)<16){hoverId=p.node.id;canvas.style.cursor='pointer';$('#tooltip').hidden=false;$('#tooltip').textContent=p.node.title;$('#tooltip').style.left=Math.min(width-220,x+14)+'px';$('#tooltip').style.top=Math.max(10,y-35)+'px';}else{hoverId='';canvas.style.cursor='grab';$('#tooltip').hidden=true;}
});
canvas.addEventListener('pointerup',e=>{if(!dragged){const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;const p=projected.filter(p=>p.node.type==='event').find(p=>Math.hypot(p.x-x,p.y-y)<17);if(p){selectedId=p.node.id;renderInspector();pulseAt(selectedId);}}pointer=null;});
canvas.addEventListener('pointercancel',()=>pointer=null);canvas.addEventListener('pointerleave',()=>{$('#tooltip').hidden=true;});
canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.7,Math.min(1.6,zoom-e.deltaY*.0007));},{passive:false});
resize();initialize();requestAnimationFrame(draw);
