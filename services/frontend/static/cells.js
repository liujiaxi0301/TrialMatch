/* Decorative cell field. Animation follows request lifecycle, never its outcome or score. */
(() => {
  'use strict';
  const canvas = document.getElementById('cellField');
  const toggle = document.getElementById('motionToggle');
  const ctx = canvas.getContext('2d');
  if (!ctx) { toggle.hidden = true; return; }
  const preference = matchMedia('(prefers-reduced-motion: reduce)');
  let paused = preference.matches, width = 0, height = 0, frame = 0;
  let last = 0, clock = 0, energy = 0, pulse = 0, active = false;
  const pointer = {x: -1000, y: -1000};
  const cells = Array.from({length: 19}, (_, i) => ({
    x: (i * .61803398875 + .13) % 1, y: (i * .427193 + .07) % 1,
    r: 25 + (i * 37 % 83), phase: i * 2.39,
    hue: i % 4 === 0 ? 256 : 164 + (i % 3) * 9,
    depth: .4 + (i % 5) * .15
  }));

  // Keep two prominent specimens in the open space beside the title.
  Object.assign(cells[0],{x:.88,y:.16,r:92,hue:168,depth:1});
  Object.assign(cells[1],{x:.77,y:.1,r:43,hue:253,depth:.85});

  function membrane(x, y, radius, phase, time) {
    ctx.beginPath();
    for (let j = 0; j <= 80; j++) {
      const angle = j / 80 * Math.PI * 2;
      const r = radius * (1 + .07 * Math.sin(angle * 3 + phase + time * .35)
        + .035 * Math.cos(angle * 5 - time * .24 + phase));
      const px = x + Math.cos(angle) * r, py = y + Math.sin(angle) * r * .87;
      if (!j) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.closePath();
  }

  function draw(dt) {
    clock += dt * (1 + energy * 2.5);
    energy += ((active ? 1 : 0) - energy) * Math.min(1, dt * 1.5);
    pulse = Math.max(0, pulse - dt * .38);
    ctx.clearRect(0, 0, width, height);
    const time = clock;
    const positions = cells.slice(0, width < 600 ? 10 : cells.length).map((c, i) => {
      const driftX = Math.sin(time * .13 + c.phase) * 45;
      const driftY = Math.cos(time * .1 + c.phase) * 40;
      const fieldWidth = Math.min(width, 2200);
      let x = (width-fieldWidth)/2 + c.x * fieldWidth + driftX, y = c.y * height + driftY;
      // A subtle current flows toward the right-hand field during screening.
      x += (width * .82 - x) * energy * .12;
      y += Math.sin(time * .6 + c.phase) * energy * 25;
      const dx = x - pointer.x, dy = y - pointer.y, dist = Math.hypot(dx, dy);
      if (!paused && dist < 170 && dist > 0) {
        x += dx / dist * (170 - dist) * .14;
        y += dy / dist * (170 - dist) * .14;
      }
      const radius = c.r * (width < 600 ? .65 : 1) * (1 + .035 * Math.sin(time + i));
      const hue = c.hue;
      const alpha = c.depth * (.42 + energy * .3 + pulse * .15);
      ctx.globalAlpha = alpha;
      const glow = ctx.createRadialGradient(x, y, radius * .25, x, y, radius * 1.6);
      glow.addColorStop(0, `hsla(${hue}, 75%, 61%, .12)`);
      glow.addColorStop(.65, `hsla(${hue}, 70%, 50%, .07)`);
      glow.addColorStop(1, `hsla(${hue}, 70%, 50%, 0)`);
      ctx.fillStyle = glow;
      ctx.fillRect(x-radius*1.6,y-radius*1.6,radius*3.2,radius*3.2);
      const fill = ctx.createRadialGradient(x-radius*.3,y-radius*.4,0,x,y,radius);
      fill.addColorStop(0, `hsla(${hue}, 60%, 62%, .09)`);
      fill.addColorStop(.75, `hsla(${hue}, 55%, 32%, .07)`);
      fill.addColorStop(1, `hsla(${hue}, 80%, 70%, .27)`);
      membrane(x,y,radius,c.phase,time);
      ctx.fillStyle=fill; ctx.fill();
      ctx.strokeStyle=`hsla(${hue}, 80%, 77%, .7)`; ctx.lineWidth=.8; ctx.stroke();
      membrane(x,y,radius*.93,c.phase,time);
      ctx.strokeStyle=`hsla(${hue}, 70%, 65%, .2)`; ctx.lineWidth=.5; ctx.stroke();
      const nx=x+Math.sin(c.phase+time*.2)*radius*.18;
      const ny=y+Math.cos(c.phase)*radius*.12;
      membrane(nx,ny,radius*.3,c.phase+2,time*.7);
      ctx.fillStyle=`hsla(${hue}, 60%, 65%, .16)`; ctx.fill();
      ctx.strokeStyle=`hsla(${hue}, 80%, 78%, .6)`; ctx.stroke();
      // Small internal organelles orbit within the membrane.
      for(let k=0;k<7;k++) {
        const a=k*2.4+c.phase+time*.04;
        const rr=radius*(.45+(k%3)*.1);
        ctx.beginPath();
        ctx.ellipse(x+Math.cos(a)*rr,y+Math.sin(a)*rr*.76,2.5+k%3,1.5,a,0,Math.PI*2);
        ctx.fillStyle=`hsla(${hue}, 65%, 76%, .55)`;ctx.fill();
      }
      return {x,y,hue};
    });
    // Fine traces emerge only during the interaction, then dissolve.
    if (energy > .04 || pulse > .04) {
      positions.forEach((p,i)=>{
        const q=positions[(i+3)%positions.length];
        if(Math.hypot(p.x-q.x,p.y-q.y)>width*.48)return;
        ctx.globalAlpha=(energy+ pulse)*.12;
        ctx.strokeStyle='#8fffe0';ctx.lineWidth=.6;
        ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.quadraticCurveTo((p.x+q.x)/2,p.y-70,q.x,q.y);ctx.stroke();
        const t=(time*.25+i*.21)%1;
        const x=(1-t)*(1-t)*p.x+2*(1-t)*t*(p.x+q.x)/2+t*t*q.x;
        const y=(1-t)*(1-t)*p.y+2*(1-t)*t*(p.y-70)+t*t*q.y;
        ctx.globalAlpha=energy*.7+pulse*.3;
        ctx.beginPath();ctx.arc(x,y,1.6,0,Math.PI*2);ctx.fillStyle='#b7ffe9';ctx.fill();
      });
    }
    ctx.globalAlpha=1;
  }
  function tick(now) {
    frame=0;
    if(document.hidden || paused)return;
    if(now-last>=30){draw(Math.min((now-last)/1000,.06));last=now;}
    frame=requestAnimationFrame(tick);
  }
  function resume() {
    cancelAnimationFrame(frame);frame=0;last=performance.now();
    if(!paused && !document.hidden)frame=requestAnimationFrame(tick);
    else draw(0);
  }
  function resize() {
    width=innerWidth;height=innerHeight;
    const dpr=Math.min(devicePixelRatio || 1,1.5);
    canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
    canvas.style.width=`${width}px`;canvas.style.height=`${height}px`;
    ctx.setTransform(dpr,0,0,dpr,0,0);draw(0);
  }
  function updateToggle() {
    document.body.dataset.motion=paused?'paused':'running';
    toggle.setAttribute('aria-pressed',String(!paused));
    toggle.textContent=paused?'Motion off':'Motion on';
    toggle.title=paused?'Enable decorative cell animation':'Pause decorative cell animation';
    resume();
  }
  toggle.addEventListener('click',()=>{paused=!paused;updateToggle();});
  preference.addEventListener('change',e=>{paused=e.matches;updateToggle();});
  document.addEventListener('visibilitychange',resume);
  window.addEventListener('resize',resize,{passive:true});
  window.addEventListener('pointermove',e=>{pointer.x=e.clientX;pointer.y=e.clientY;},{passive:true});
  document.documentElement.addEventListener('pointerleave',()=>{pointer.x=-1000;pointer.y=-1000;});
  window.addEventListener('trialmatch:activity',e=>{
    active=e.detail==='start';
    document.body.dataset.screening=active?'active':e.detail;
    if(active){energy=Math.max(energy,.8);pulse=1;}
    else {pulse=e.detail==='complete'?1:.25;}
    if(paused)draw(0);
  });
  resize();updateToggle();
})();
