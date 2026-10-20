(() => {
  if (!document.body) return null;
  const cache = window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const safe = e => !['file','hidden'].includes(e.type);
  // A password's value never leaves the page, only whether it is filled: the run types it from its own secrets.
  const val = e => e.type==='password' ? (e.value ? '[filled]' : '') : e.value;
  const visible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(document.getElementById(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (e.tagName==='INPUT' ? '' : [...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
        n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? name(n,seen) : '').join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'option','gridcell','combobox','textbox','searchbox','spinbutton'];
  const selector='a[href],button,input,textarea,select,summary,[contenteditable="true"],'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const role = e => {
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A') return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (['text','email','url','tel','password'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  // The wheel goes where a person's would, at the lower middle of the viewport, and moves the nearest element under it
  // that can still scroll that way, else the document: an app whose content scrolls inside a container (a fixed-height
  // body around an overflow:auto main) moves only that container. With nothing scrollable under that point, the largest
  // visible scroll container takes the wheel at its center.
  const docStyle=getComputedStyle(document.documentElement), bodyStyle=getComputedStyle(document.body);
  const scrollable = e => e!==document.scrollingElement && !(e===document.body && docStyle.overflowY==='visible') &&
    /auto|scroll|overlay/.test(getComputedStyle(e).overflowY) && e.scrollHeight>e.clientHeight+2;
  const scrollers = point => {
    const chain=[];
    for (let e=document.elementFromPoint(point.x,point.y); e && e!==document.documentElement; e=e.parentElement)
      if (scrollable(e)) chain.push(e);
    return chain;
  };
  const docHeight=document.documentElement.scrollHeight;
  const docLocked=docStyle.overflowY==='hidden' || (docStyle.overflowY==='visible' && bodyStyle.overflowY==='hidden');
  const docDown=!docLocked && scrollY+innerHeight<docHeight-2, docUp=!docLocked && scrollY>0;
  cache.point={x:550,y:650};  // of the 1120x780 viewport browser.py sets
  if (!scrollers(cache.point).length && !docDown && !docUp) {
    let best=null, area=0;
    for (const e of document.body.querySelectorAll('*')) {
      if (e.scrollHeight<=e.clientHeight+2 || !scrollable(e)) continue;
      const r=e.getBoundingClientRect(), w=Math.min(r.right,innerWidth)-Math.max(r.left,0),
        h=Math.min(r.bottom,innerHeight)-Math.max(r.top,0);
      if (w>0 && h>0 && w*h>area) [best,area]=[{x:Math.round(Math.max(r.left,0)+w/2),y:Math.round(Math.max(r.top,0)+h/2)},w*h];
    }
    if (best) cache.point=best;
  }
  cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    [...document.querySelectorAll('input,textarea,select')].filter(safe)
      .map(e=>[identity(e),val(e),e.checked,e.selectedIndex,e.disabled,e.readOnly]),
    scrollers(cache.point).map(e=>[identity(e),Math.round(e.scrollTop)])];
  cache.guard=e=>{
    if (!e?.isConnected || !visible(e)) return null;
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e),role(e),name(e),val(e)??null,e.checked??null,e.selectedIndex??null,
      e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),scope?.innerText?.slice(0,6000)||''];
  };
  const actions=[];
  for (const e of document.querySelectorAll(selector)) {
    if (!safe(e) || !visible(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
    const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2, rname=role(e);
    if (!rname || r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight) continue;
    if (rname==='gridcell' && e.querySelector('button,[role="button"]')) continue;
    const base={node:identity(e),role:rname,label:name(e)||rname,
      rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
    for (const key of ['checked','selected','expanded']) {
      const value=e.getAttribute('aria-'+key);
      if (value!==null) base[key]=value;
    }
    if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
    if (e.type==='password') base.secret=true;
    if (e.tagName==='SELECT') {
      for (const o of e.options) if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        actions.push({...base,kind:'select',value:o.value,
          current_value:[...e.selectedOptions].map(o=>o.label).join(', '),label:base.label+' → '+o.label});
    } else {
      const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(rname) ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      const value='value' in e ? String(val(e)) :
        e.isContentEditable || rname==='combobox' ? e.innerText.trim() : '';
      actions.push({...base,kind:editable?'fill':'click',value});
      if (editable) actions.push({...base,kind:'click',value,label:'Open '+base.label});
    }
  }
  // Not actions, but the model needs them: a disabled Submit says the form still waits for something, and an
  // unanswered question (also offscreen) says what. Without them the model skipped a question and looped.
  const where = e => {
    const r=e.getBoundingClientRect();
    return r.bottom<=0 ? ', above the visible area' : r.top>=innerHeight ? ', below the visible area' : '';
  };
  const disabled=[];
  for (const e of document.querySelectorAll(selector)) {
    if (disabled.length>=20 || !safe(e) || !visible(e) || !role(e)) continue;
    if (!e.matches(':disabled') && !e.closest('[aria-disabled="true"]')) continue;
    const r=e.getBoundingClientRect();
    if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight)
      disabled.push(role(e)+' '+(name(e)||role(e))+' [disabled]');
  }
  const unanswered=[], groups=new Map();
  for (const e of document.querySelectorAll('input[type="radio"],[role="radio"]')) {
    if (!visible(e) || e.matches(':disabled')) continue;
    const key=e.name && e.tagName==='INPUT' ?
      (e.form||document).querySelector('input[type="radio"][name="'+CSS.escape(e.name)+'"]') :
      e.closest('[role="radiogroup"]') || e;
    if (!groups.has(key)) groups.set(key,{first:e,checked:false});
    if (e.checked || e.getAttribute('aria-checked')==='true') groups.get(key).checked=true;
  }
  for (const {first,checked} of groups.values()) {
    if (checked) continue;
    const legend=first.closest('fieldset')?.querySelector('legend'), group=first.closest('[role="radiogroup"]');
    const label=(group && name(group)) || (legend && name(legend)) || first.name || name(first);
    unanswered.push(label+' [no option selected'+where(first)+']');
  }
  for (const e of document.querySelectorAll('input,textarea,select,[aria-required="true"]')) {
    if (!safe(e) || e.type==='radio' || !visible(e) || e.matches(':disabled')) continue;
    const required=e.required || e.getAttribute('aria-required')==='true';
    // Script-validated forms rarely mark fields required; a locked submit says its form's empty fields may count.
    const locked=!required && !e.readOnly && e.form?.querySelector('button:disabled,input[type="submit"]:disabled') &&
      ['textbox','searchbox','spinbutton','combobox'].includes(role(e));
    if (!required && !locked) continue;
    const empty=e.type==='checkbox' ? !e.checked : 'value' in e ? !String(e.value).trim() : !e.innerText.trim();
    if (empty) unanswered.push((name(e)||role(e)||'field')+' ['+(required ? 'required, ' : '')+
      (e.type==='checkbox' ? 'unchecked' : 'empty')+where(e)+']');
  }
  unanswered.splice(20);
  const words=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const range=document.createRange(); let node,length=0;
  while ((node=walker.nextNode()) && length<6000) {
    const value=node.textContent.trim(), parent=node.parentElement;
    if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
    range.selectNodeContents(node); const r=range.getBoundingClientRect();
    if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth) {
      words.push(value); length+=value.length;
    }
  }
  const text=words.join('\n').slice(0,6000);
  const page_key=cache.pageKey(), guards={};
  for (const a of actions) if (!(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
  // Compare meaning and identity. Geometry is always resolved and hit-tested just before input.
  const semantics=actions.map(({rect,...action})=>action);
  const marker=[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,semantics,page_key[6],page_key[7],disabled,unanswered];
  const omitted_actions=Math.max(0,actions.length-250);
  actions.splice(250);
  actions.forEach((a,i)=>a.id='e'+(i+1));
  // A step is about 70% of what it moves, so the next view keeps a little of the last one in sight.
  const chain=scrollers(cache.point), step=e=>Math.round(Math.min(560,0.72*(e ? e.clientHeight : innerHeight)));
  const down=chain.find(e=>e.scrollTop+e.clientHeight<e.scrollHeight-2), up=chain.find(e=>e.scrollTop>0);
  if (down || docDown) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down',delta:step(down),...cache.point});
  if (up || docUp) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-step(up),...cache.point});
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  return {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text,
    scroll:{y:scrollY,height:docHeight,inner:page_key[7].map(([,top])=>top)},actions,disabled,unanswered,marker,page_key,guards,omitted_actions};
})()
