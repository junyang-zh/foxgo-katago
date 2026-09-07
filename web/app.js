'use strict';
const $ = id => document.getElementById(id);
const letters = 'ABCDEFGHJKLMNOPQRST';
const NS = 'http://www.w3.org/2000/svg';
let state, reviewing = null, pending = false, selectedChoice = null, focusPoint = null, lastNotice = '', lastBoardKey = '';
let selectedConnector = null, switchingConnector = false;
function renderConnector() {
  const active=state.mode!=='local';
  if(active)selectedConnector=state.mode==='vision'?'vision':state.connector;
  else if(selectedConnector===null)selectedConnector=['direct','foxgtp','vision'].includes(state.connector)?state.connector:'direct';
  $('connector-type').value=selectedConnector;
  $('tcp-controls').hidden=selectedConnector==='vision';
  $('vision-controls').hidden=selectedConnector!=='vision';
  $('direct-status-controls').hidden=selectedConnector!=='direct';
  $('direct-guide').hidden=selectedConnector!=='direct';
  $('relay-guide').hidden=selectedConnector!=='foxgtp';
  $('tcp-method-detail').textContent=selectedConnector==='foxgtp'?'FoxGo → FoxGTP port 6001 → trainer port 8001.':'FoxGo → trainer TCP port 6001.';
  $('connector-help').textContent=switchingConnector?'Stopping the current connection…':active?'Selecting another method stops this connection first.':'Choose one method. Only its controls are shown.';
}
function node(tag, attrs = {}, text = '') {
  const el = document.createElementNS(NS, tag);
  for (const [k,v] of Object.entries(attrs)) el.setAttribute(k,v);
  if (text) el.textContent = text;
  return el;
}
function coordinate(v) {
  const m = /^([A-HJ-T])(\d+)$/.exec(v || '');
  return m ? [letters.indexOf(m[1]),state.size-Number(m[2])] : null;
}
function showNotice(text, error = false) {
  $('notice').textContent = text;
  $('notice').classList.toggle('error',error);
  if (error) lastNotice = text;
}
async function action(name, data = {}) {
  if (pending) return false;
  pending = true; lastNotice = ''; renderControls();
  showNotice(name === 'engine-connect' ? 'Starting KataGo. First GPU initialization may take a minute…' : 'Working…');
  try {
    const response = await fetch('/api/action/' + name, {method:'POST',headers:{'Content-Type':'application/json','X-Trainer-Token':state.token},body:JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Request failed.');
    state = result; reviewing = null; selectedChoice = null; lastBoardKey = '';
    render(); return true;
  } catch (error) {
    showNotice(error.message,true);
    if ($('settings-dialog').open) $('settings-error').textContent = error.message;
    return false;
  } finally { pending = false; renderControls(); }
}
function atMove() {return reviewing === null ? state.moves.length : Math.min(reviewing,state.moves.length);}
function currentAnalysis() {return state.analyses?.[atMove()] || (state.analysis?.moveNumber === atMove() ? state.analysis : {});}
function territoryAnalysis() {
  const move=atMove();
  return [...Object.values(state.analyses||{}),state.analysis||{}]
    .filter(a=>Number.isInteger(a.moveNumber)&&a.moveNumber<=move&&
      ['B','W'].includes(a.turn)&&a.ownership?.length===state.size*state.size)
    .sort((a,b)=>b.moveNumber-a.moveNumber)[0]||{};
}
function renderBoard() {
  const move = atMove(), snapshot = state.history[move] || state.history.at(-1), analysis = currentAnalysis();
  const territory=territoryAnalysis();
  const key = JSON.stringify([state.revision,move,analysis,territory,$('hints').checked,$('ownership').checked,selectedChoice,focusPoint,state.grid]);
  if (key === lastBoardKey) return;
  lastBoardKey = key;
  const svg = $('board'); svg.replaceChildren();
  const defs = node('defs');
  for (const [id,colors] of [['blackStone',['#586068','#1e252b','#0c1015']],['whiteStone',['#ffffff','#edece6','#c1bdae']]]) {
    const gradient = node('radialGradient',{id,cx:'32%',cy:'25%',r:'75%'});
    colors.forEach((c,i)=>gradient.append(node('stop',{offset:`${i*50}%`,'stop-color':c})));
    defs.append(gradient);
  }
  svg.append(defs,node('rect',{width:760,height:760,fill:'#d7ad71'}));
  const n=state.size, margin=42, step=676/(n-1), r=step*.455;
  for(let i=0;i<n;i++) {
    const z=margin+i*step;
    svg.append(node('line',{x1:margin,y1:z,x2:718,y2:z,class:'grid-line'}),node('line',{x1:z,y1:margin,x2:z,y2:718,class:'grid-line'}));
    svg.append(node('text',{x:z,y:19,class:'board-label'},letters[i]),node('text',{x:z,y:743,class:'board-label'},letters[i]),node('text',{x:18,y:z,class:'board-label'},String(n-i)),node('text',{x:743,y:z,class:'board-label'},String(n-i)));
  }
  const stars=n===19?[3,9,15]:n===13?[3,6,9]:[2,4,6];
  for(const y of stars) for(const x of stars) if(n!==9 || x===y || x+y===8) svg.append(node('circle',{cx:margin+x*step,cy:margin+y*step,r:n===19?3.3:4,fill:'#6d4e2c'}));
  const own=territory.ownership || [];
  $('territory-status').hidden=!$('ownership').checked;
  $('territory-status').textContent=own.length?`Territory · ${territory.moveNumber===move?'estimate':'latest estimate'} at move ${territory.moveNumber+(state.moveOffset||0)}`:'Territory · waiting for the first analysis';
  if($('ownership').checked && own.length===n*n) own.forEach((v,i)=>{
    const black=territory.turn==='B'?v:-v;
    if(Math.abs(black)>.15) svg.append(node('rect',{x:margin+(i%n)*step-step*.22,y:margin+Math.floor(i/n)*step-step*.22,width:step*.44,height:step*.44,fill:black>0?'#17232a':'#fff',opacity:Math.abs(black)*.65}));
  });
  for(let y=0;y<n;y++) for(let x=0;x<n;x++) if(snapshot.grid[y][x]) svg.append(node('circle',{cx:margin+x*step,cy:margin+y*step,r,class:snapshot.grid[y][x]==='B'?'stone-b':'stone-w'}));
  if(move>0) {
    const p=coordinate(state.moves[move-1][1]);
    if(p) svg.append(node('circle',{cx:margin+p[0]*step,cy:margin+p[1]*step,r:r*.35,class:'last-move'}));
  }
  if($('hints').checked && selectedChoice===null) (analysis.choices||[]).slice(0,5).forEach((c,i)=>{
    const p=coordinate(c.move); if(!p || snapshot.grid[p[1]]?.[p[0]]) return;
    const x=margin+p[0]*step,y=margin+p[1]*step;
    svg.append(node('circle',{cx:x,cy:y,r:r*.85,class:'candidate'+(i===0?' best':'')}),node('text',{x,y,class:'candidate-text'},String(i+1)));
  });
  if(selectedChoice!==null && analysis.choices?.[selectedChoice]) {
    const occupied=snapshot.grid.map(row=>row.slice());
    let c=analysis.turn;
    (analysis.choices[selectedChoice].pv||[]).slice(0,10).forEach((v,i)=>{
      const p=coordinate(v);
      if(p && !occupied[p[1]]?.[p[0]]) {
        occupied[p[1]][p[0]]=c;
        svg.append(node('circle',{cx:margin+p[0]*step,cy:margin+p[1]*step,r,class:c==='B'?'stone-b':'stone-w',opacity:.8}),node('text',{x:margin+p[0]*step,y:margin+p[1]*step,fill:c==='B'?'#fff':'#14242a',class:'pv-number'},String(i+1)));
      }
      c=c==='B'?'W':'B';
    });
  }
  if(focusPoint) svg.append(node('circle',{cx:margin+focusPoint[0]*step,cy:margin+focusPoint[1]*step,r:r*.75,class:'focus-point'}));
  $('review-banner').hidden=reviewing===null;
}
function renderChart() {
  const curve=$('curve'); curve.replaceChildren();
  const samples=Object.values(state.evaluations).sort((a,b)=>a.move-b.move), end=Math.max(1,state.moves.length);
  const x=m=>36+m/end*425, y=v=>142-v*118;
  [0,.5,1].forEach(v=>curve.append(node('line',{x1:36,x2:461,y1:y(v),y2:y(v),class:'chart-grid'}),node('text',{x:0,y:y(v)+4,class:'chart-text'},`${v*100}%`)));
  const maxScore=Math.max(10,...samples.map(s=>Math.ceil(Math.abs(s.blackScore)/10)*10));
  const scoreY=v=>83-v/maxScore*59;
  curve.append(node('text',{x:467,y:28,class:'chart-text'},`+${maxScore}`),node('text',{x:467,y:146,class:'chart-text'},`−${maxScore}`));
  if(samples.length) {
    for(const [value,col,scale] of [['blackWinrate','#79d8aa',y],['blackScore','#e4b46d',scoreY]]) {
      curve.append(node('polyline',{points:samples.map(s=>`${x(s.move)},${scale(s[value])}`).join(' '),fill:'none',stroke:col,'stroke-width':2}));
      samples.forEach(s=>curve.append(node('circle',{cx:x(s.move),cy:scale(s[value]),r:2.7,fill:col})));
    }
    curve.append(node('line',{x1:x(atMove()),x2:x(atMove()),y1:15,y2:150,stroke:'#dce7e5','stroke-opacity':'.5'}));
  }
  const current=state.evaluations[atMove()];
  $('winrate').textContent=current?`${(current.blackWinrate*100).toFixed(1)}%`:'—';
  $('score').textContent=current?`${current.blackScore>=0?'B':'W'} +${Math.abs(current.blackScore).toFixed(1)}`:'—';
  $('win-fill').style.width=`${current?current.blackWinrate*100:50}%`;
  $('chart-caption').textContent=samples.length?`${samples.length} evaluated positions · Black perspective${state.moveOffset?` · tracked from move ${state.moveOffset}`:''}`:'Analysis appears after a KataGo search.';
  const previous=state.evaluations[atMove()-1], last=state.moves[atMove()-1];
  $('feedback').textContent=current&&previous&&last?`${last[0]==='B'?'Black':'White'} ${last[1]}: ${((previous.blackScore-current.blackScore)*(last[0]==='B'?1:-1)).toFixed(1)} estimated points lost. Compare candidate continuations.`:'Move the timeline to review earlier positions. Dots mark evaluated positions; lines connect samples.';
}
function renderChoices() {
  const a=currentAnalysis(), choices=a.choices||[], box=$('choices'); box.replaceChildren();
  $('choice-turn').textContent=a.turn?`${a.turn==='B'?'Black':'White'} to play · #${a.moveNumber+(state.moveOffset||0)}`:'No analysis';
  $('visits').textContent=a.root?`${Math.round(a.root.visits||0).toLocaleString()} visits`:state.engine?'Ready':'Awaiting engine';
  if(!choices.length) {const p=document.createElement('p');p.className='empty';p.textContent=state.engine?'No candidate analysis for this position. Analyze the live board, or wait for the next AI search.':'Connect KataGo to explore candidate moves, winrates and continuations.';box.append(p);}
  choices.slice(0,5).forEach((c,i)=>{
    const b=document.createElement('button'); b.className='choice';b.title='Preview continuation (does not play a move)';
    for(const [text,sub,cls] of [[String(i+1),'','choice-rank'],[c.move,`${Math.round(c.visits||0).toLocaleString()} visits`,''],[`${((c.winrate||0)*100).toFixed(1)}%`,'winrate',''],[`${Number(c.scoreLead??c.scoreMean??0).toFixed(1)}`,'points ahead','']]) {
      const span=document.createElement('span');span.textContent=text;span.className=cls;
      if(sub) {const small=document.createElement('small');small.textContent=sub;span.append(small);} b.append(span);
    }
    b.onclick=()=>{selectedChoice=selectedChoice===i?null:i;renderChoices();renderBoard();};box.append(b);
  });
  $('pv').hidden=selectedChoice===null || !choices[selectedChoice];
  if(!$('pv').hidden) $('pv').textContent=`Continuation: ${(choices[selectedChoice].pv||[]).slice(0,10).join(' → ')}. Numbered stones preview the first 10 moves; captures in variations are not simulated. Click the choice again to close.`;
}
function renderControls() {
  if(!state) return;
  renderConnector();
  $('heart-opening').checked=!!state.settings.heartOpening;
  $('heart-opening').disabled=pending||!!state.busy||state.mode!=='local';
  $('heart-status').textContent=state.entertainment?.status||'Restart backend to load entertainment mode';
  const busy=pending||!!state.busy, online=state.mode!=='local';
  document.querySelectorAll('[data-local]').forEach(b=>b.disabled=busy||online||reviewing!==null);
  document.querySelectorAll('[data-engine]').forEach(b=>b.disabled=b.disabled||!state.engine);
  $('settings-open').disabled=busy||online;
  $('fox-toggle').disabled=state.mode==='vision'||pending||(!online&&busy);
  $('connector-type').disabled=pending||switchingConnector;
  $('fox-reserve').disabled=online||busy;
  $('fox-sync').disabled=pending||!state.foxConnected||state.connector!=='direct';
  $('fox-port').disabled=online||busy;
  $('busy-label').textContent=state.busy?' / '+state.busy:'';
  window.renderVision?.(state);
}
function render() {
  if(!state) return;
  $('engine-status').textContent=state.engine?'KataGo connected':'KataGo offline';
  $('engine-dot').classList.toggle('on',state.engine);
  $('mode-label').textContent=state.mode==='vision'?'FOXGO · SCREEN CONNECTOR':state.mode==='online'?'FOXGO · ONLINE OBSERVER':'LOCAL PRACTICE';
  const snap=state.history[atMove()]||state.history.at(-1);
  const aiColor=state.mode==='vision'?state.vision.aiColor:state.mode==='online'?state.foxGame?.aiColor:state.settings.aiColor;
  $('turn-label').textContent=state.result&&reviewing===null?state.result:`${snap.turn==='B'?'Black':'White'} to play`;
  $('black-info').textContent=`${snap.captures.B} captures${state.moveOffset?' since attachment':''}${aiColor==='B'?' · AI':''}`;
  $('white-info').textContent=`${snap.captures.W} captures${state.moveOffset?' since attachment':''}${aiColor==='W'?' · AI':''}`;
  $('game-meta').textContent=`${state.size} × ${state.size} · ${state.rules==='chinese'?'Chinese':'Japanese'} · Komi ${state.komi}`;
  $('history').max=state.moves.length; $('history').value=atMove();
  $('move-number').textContent=`Move ${atMove()+(state.moveOffset||0)} / ${state.moves.length+(state.moveOffset||0)}`;
  $('fox-status').textContent=state.foxConnected?((state.connector==='foxgtp'?'FoxGTP':'FoxGo')+(state.foxReady?' synced':' connected')):state.mode==='online'?'Listening':'Offline';
  $('fox-toggle').textContent=state.mode==='online'?'Stop listener':'Start listener';
  const fg=state.connector==='foxgtp'&&state.mode==='online'?{status:state.foxConnected?(state.foxReady?'FoxGTP game synchronized':'FoxGTP connected · waiting for game commands'):'Waiting for FoxGTP on the engine port'}:state.foxGame||{};
  $('fox-detail').textContent=[fg.status,fg.aiColor?`AI ${fg.aiColor} · main ${fg.mainTime}s · byo ${fg.byoTime}s × ${fg.periods}`:'',fg.pendingMove?`Awaiting confirmation: ${fg.pendingMove}`:''].filter(Boolean).join(' · ');
  if(state.mode==='online') {$('fox-reserve').value=state.foxReserve;$('fox-port').value=state.foxPort;$('connector-type').value=state.connector;}
  renderBoard();renderChart();renderChoices();renderControls();renderLogs();
  if(!lastNotice&&!pending) showNotice(state.busy?`Working: ${state.busy}…`:reviewing!==null?'Review mode. Return to Live to play.':state.mode==='online'?'Online observer: FoxGo controls the game.':state.mode==='vision'?(state.vision.status||'Reading FoxGo…'):state.result||(!state.engine?'Two-player practice is available. Connect KataGo for AI play and analysis.':'Click an intersection to play. Candidate numbers show KataGo’s preferred moves.'));
}
function renderLogs() {
  const box=$('logs'), bottom=box.scrollTop+box.clientHeight>=box.scrollHeight-25;
  const logs=$('debug').checked?state.logs:state.logs.filter(l=>['info','error','warning','fox','score','fox score','vision'].includes(l.level));
  box.replaceChildren();
  logs.slice(-100).forEach(l=>{const row=document.createElement('div');row.className='log-row'+(l.level==='error'?' error':'');[l.time,l.level,l.message].forEach((s,i)=>{const span=document.createElement('span');span.className=['log-time','log-level','log-message'][i];span.textContent=s;row.append(span);});box.append(row);});
  if(bottom) box.scrollTop=box.scrollHeight;
}
let backendOffline = false;
async function poll() {
  try {const r=await fetch('/api/state');if(!r.ok) throw Error('Server unavailable');state=await r.json();if(backendOffline){lastNotice='';backendOffline=false;}render();}
  catch {
    backendOffline = true;
    $('engine-status').textContent='Local server disconnected';$('engine-dot').classList.remove('on');
    $('fox-status').textContent='Backend offline';
    $('fox-detail').textContent='The trainer cannot receive or play moves until its backend is restarted.';
    showNotice('Trainer backend offline. Start the server, then reconnect FoxGo to its AI listener.',true);
  }
  setTimeout(poll,900);
}
function playPoint(x,y) {
  if(!state || pending || state.busy || state.mode!=='local'||reviewing!==null) return;
  action('play',{vertex:letters[x]+(state.size-y)});
}
$('board').addEventListener('click',event=>{
  if(!state)return; const rect=$('board').getBoundingClientRect(),step=676/(state.size-1);
  const x=Math.round(((event.clientX-rect.left)/rect.width*760-42)/step),y=Math.round(((event.clientY-rect.top)/rect.height*760-42)/step);
  if(x>=0&&y>=0&&x<state.size&&y<state.size) playPoint(x,y);
});
$('board').addEventListener('keydown',event=>{
  if(!state)return;if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Enter',' '].includes(event.key))return;
  event.preventDefault();focusPoint ||= [Math.floor(state.size/2),Math.floor(state.size/2)];
  if(event.key==='Enter'||event.key===' ')playPoint(...focusPoint);
  else {const axis=event.key==='ArrowLeft'||event.key==='ArrowRight'?0:1;focusPoint[axis]=Math.max(0,Math.min(state.size-1,focusPoint[axis]+(['ArrowLeft','ArrowUp'].includes(event.key)?-1:1)));renderBoard();}
});
$('board').addEventListener('blur',()=>{focusPoint=null;if(state)renderBoard();});
document.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>{if(b.dataset.action==='resign'&&!confirm('Resign this local game?'))return;action(b.dataset.action);});
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$(b.dataset.close).close());
$('settings-open').onclick=()=>{for(const [k,v] of Object.entries(state.settings)){const e=$('settings-form').elements.namedItem(k);if(e)e.value=v;}$('settings-error').textContent='';$('settings-dialog').showModal();};
$('settings-form').onsubmit=async e=>{e.preventDefault();$('settings-error').textContent='';if(await action('engine-connect',Object.fromEntries(new FormData(e.target))))$('settings-dialog').close();};
$('engine-stop').onclick=async()=>{if(await action('engine-stop'))$('settings-dialog').close();};
$('new-open').onclick=()=>$('new-dialog').showModal();
$('new-form').onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));$('new-dialog').close();await action('new',data);};
$('connector-type').onchange=async()=>{
  if(!state||pending||switchingConnector){if(state)renderControls();return;}
  const requested=$('connector-type').value;
  if(requested===selectedConnector)return;
  switchingConnector=true;
  try {
    if(state.mode!=='local'&&!await action(state.mode==='vision'?'vision-stop':'fox-stop'))return;
    selectedConnector=requested;
    if(selectedConnector!=='vision')$('fox-port').value=selectedConnector==='foxgtp'?8001:6001;
  } finally {switchingConnector=false;renderControls();}
};
$('fox-sync').onclick=()=>action('fox-sync',{color:$('fox-color').value});
$('fox-toggle').onclick=()=>action(state.mode==='online'?'fox-stop':'fox-start',{port:Number($('fox-port').value),reserve:Number($('fox-reserve').value),connector:$('connector-type').value});
function review(n){reviewing=Math.max(0,Math.min(state.moves.length,n));selectedChoice=null;render();}
$('history').oninput=e=>review(Number(e.target.value));$('back').onclick=()=>review(atMove()-1);$('forward').onclick=()=>review(atMove()+1);
$('live').onclick=()=>{reviewing=null;selectedChoice=null;render();};
$('hints').onchange=renderBoard;$('ownership').onchange=renderBoard;$('debug').onchange=renderLogs;
poll();

// Optional imperative WebMCP surface; ordinary browsers need no polyfill.
if (document.modelContext?.registerTool) {
  const lifecycle = new AbortController();
  const register = tool => {
    try {Promise.resolve(document.modelContext.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});}
    catch { /* Experimental API unavailable in this browser. */ }
  };
  register({name:'read_go_position',description:'Read the current local or FoxGo game position and engine status.',
    inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true},
    execute:()=>{if(!state)throw Error('Trainer is loading.');return {size:state.size,turn:state.turn,moves:state.moves,mode:state.mode,engine:state.engine};}});
  register({name:'play_local_go_move',description:'Play a move in the live local game, including a configured automatic KataGo reply. Not available in online or history mode.',
    inputSchema:{type:'object',properties:{vertex:{type:'string'}},required:['vertex'],additionalProperties:false},annotations:{readOnlyHint:false},
    execute:async input=>{
      if(!input||Object.keys(input).length!==1||typeof input.vertex!=='string'||!/^([A-HJ-T][1-9][0-9]?|pass)$/i.test(input.vertex))throw Error('Provide a Go coordinate or pass.');
      if(!state||state.mode!=='local'||reviewing!==null||pending||state.busy)throw Error('Return to an idle live local game first.');
      if(!await action('play',{vertex:input.vertex.toUpperCase()}))throw Error(lastNotice||'Move failed.');
      return {moveNumber:state.moves.length,turn:state.turn};
    }});
  window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
}

$('heart-opening').onchange=async e=>{await action('entertainment-settings',{enabled:e.target.checked});renderControls();};
