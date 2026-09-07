'use strict';
let visionImage=null, visionLoading=false, visionLoadedAt=0;
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
 }
$('vision-start').onclick=()=>action('vision-start',{presence:$('vision-presence').value==='on',presencePort:Number($('vision-presence-port').value)});
let presenceLoaded=false;
$('vision-presence').onchange=()=>{$('vision-presence-port-label').hidden=$('vision-presence').value!=='on';};
$('vision-arm').onclick=()=>action('vision-arm');
$('vision-pause').onclick=()=>action('vision-pause');
$('vision-stop').onclick=()=>action('vision-stop');
$('vision-pass').onclick=()=>{if(confirm('Confirm that the player whose turn is shown actually passed in FoxGo?'))action('vision-pass');};
window.renderVision=s=>{
  const v=s.vision||{}, running=!!v.running;
  if(!presenceLoaded){$('vision-presence').value=s.settings.visionPresence?'on':'off';$('vision-presence-port').value=s.settings.visionPresencePort||6001;presenceLoaded=true;}
  const presenceSupported=Object.prototype.hasOwnProperty.call(s,'presence');
  $('vision-presence').disabled=pending||running||!presenceSupported;
  $('vision-presence-port').disabled=pending||running||!presenceSupported;
  $('vision-presence-port-label').hidden=$('vision-presence').value!=='on';
  const p=s.presence||{};
  $('vision-presence-status').textContent=!presenceSupported?'Backend update required: restart the trainer to enable the AI presence listener.':p.listening?`${p.connected?'FoxGo connected':'Listening'} at 127.0.0.1:${p.port} · CV controls moves${p.lastMessage?' · '+p.lastMessage:''}`:($('vision-presence').value==='on'?'Starts with screen tracking. Stop tracking to change this option.':'AI presence listener off');
  $('vision-badge').textContent=v.armed?'Automatic moves enabled':running?'Preview / paused':'Stopped';
  $('vision-status').textContent=[v.status,v.historyNote,v.confidence!==undefined?`Minimum confidence ${(v.confidence*100).toFixed(0)}%`:'',v.pendingMove?`Pending ${v.pendingMove}`:''].filter(Boolean).join(' · ');
  $('vision-role').textContent=v.roleStatus||'Waiting to identify your account in FoxGo';
  $('vision-start').disabled=pending||running||s.mode==='online';
  $('vision-arm').disabled=pending||v.armed||s.mode==='online';
  $('vision-arm').hidden=!running||v.armed;
  $('vision-start').hidden=running;
  $('vision-arm').textContent=v.armed?'Automatic moves enabled':running?'Resume automatic moves':'Enable automatic moves';
  $('vision-pause').disabled=!running;$('vision-stop').disabled=pending||!running;
  $('vision-pass').disabled=pending||!running||v.armed||!!v.pendingMove;
  if(running&&Date.now()-visionLoadedAt>900)loadVisionImage();
  drawVision(s);
};
