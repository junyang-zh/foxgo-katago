'use strict';
let visionImage=null, visionCorners=[], visionLoading=false, visionLoadedAt=0;
function loadVisionImage() {
  if(visionLoading)return;
  visionLoading=true;
  const im=new Image();
  im.onload=()=>{visionImage=im;vc.width=im.width;vc.height=im.height;visionLoading=false;visionLoadedAt=Date.now();drawVision();};
  im.onerror=()=>{visionLoading=false;visionLoadedAt=Date.now();};
  im.src='/api/vision-image?t='+Date.now();
}
const vc=document.getElementById('vision-canvas'), vx=vc.getContext('2d');
function drawVision(s=state) {
  vx.clearRect(0,0,vc.width,vc.height);
  if(visionImage)vx.drawImage(visionImage,0,0);
  const cfg=s?.vision?.calibration, grid=s?.vision?.grid;
  if(cfg&&grid)for(let y=0;y<cfg.size;y++)for(let x=0;x<cfg.size;x++){
    vx.beginPath();vx.arc(cfg.x0+x*cfg.dx,cfg.y0+y*cfg.dy,cfg.dx*.38,0,Math.PI*2);
    vx.strokeStyle=grid[y][x]==='?'?'#ff5252':grid[y][x]==='B'?'#00bfff':grid[y][x]==='W'?'#ff4fcd':'#3ecf8e';vx.lineWidth=2;vx.stroke();
  }
  for(const p of visionCorners){vx.beginPath();vx.arc(p.x,p.y,6,0,Math.PI*2);vx.fillStyle='#ff5252';vx.fill();}
}
vc.onclick=e=>{
  if(!visionImage||state?.vision?.running)return;
  if(visionCorners.length===2)visionCorners=[];
  const r=vc.getBoundingClientRect();visionCorners.push({x:(e.clientX-r.left)*vc.width/r.width,y:(e.clientY-r.top)*vc.height/r.height});
  $('vision-corners').textContent=visionCorners.map(p=>`${p.x.toFixed(1)}, ${p.y.toFixed(1)}`).join(' → ');drawVision();
};
$('vision-windows').onclick=async()=>{
  if(await action('vision-windows')){
    $('vision-window').replaceChildren(...(state.windows||[]).map(w=>{const o=document.createElement('option');o.value=w.hwnd;o.textContent=w.title;return o;}));
  }
};
$('vision-capture').onclick=async()=>{
  if(await action('vision-capture',{hwnd:Number($('vision-window').value)})){
    visionCorners=[];loadVisionImage();
  }
};
$('vision-calibrate').onclick=()=>{
  if(visionCorners.length!==2){showNotice('Select both grid corners in the screenshot.',true);return;}
  action('vision-calibrate',{size:Number($('vision-size').value),x0:visionCorners[0].x,y0:visionCorners[0].y,x1:visionCorners[1].x,y1:visionCorners[1].y});
};
const startVision=()=>action('vision-start',{hwnd:Number($('vision-window').value),size:Number($('vision-size').value),color:$('vision-color').value,komi:Number($('vision-komi').value)});
$('vision-start').onclick=startVision;
$('vision-arm').onclick=()=>state?.vision?.running?action('vision-arm'):startVision();
$('vision-pause').onclick=()=>action('vision-pause');
$('vision-stop').onclick=()=>action('vision-stop');
$('vision-pass').onclick=()=>{if(confirm('Confirm that the player whose turn is shown actually passed in FoxGo?'))action('vision-pass');};
window.renderVision=s=>{
  const v=s.vision||{}, running=!!v.running;
  $('vision-badge').textContent=v.armed?'Automatic moves enabled':running?'Preview / paused':'Stopped';
  $('vision-status').textContent=[v.status,v.confidence!==undefined?`Minimum confidence ${(v.confidence*100).toFixed(0)}%`:'',v.pendingMove?`Pending ${v.pendingMove}`:''].filter(Boolean).join(' · ');
  for(const id of ['vision-windows','vision-capture','vision-calibrate'])$(id).disabled=pending||running||s.mode==='online';
  $('vision-start').disabled=pending||running||!s.engine||s.mode==='online';
  $('vision-arm').disabled=pending||v.armed||!s.engine||s.mode==='online';
  $('vision-arm').textContent=v.armed?'Automatic moves enabled':running?'Resume automatic moves':'Enable automatic moves';
  $('vision-pause').disabled=!running;$('vision-stop').disabled=pending||!running;
  $('vision-pass').disabled=pending||!running||v.armed||!!v.pendingMove;
  if(running&&Date.now()-visionLoadedAt>900)loadVisionImage();
  drawVision(s);
};
