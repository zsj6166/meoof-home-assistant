function meoofEntityByRole(hass, role, configured) {
  if (configured && hass.states[configured]) return hass.states[configured];
  return Object.values(hass.states).find(state => state.attributes?.meoof_card_role === role);
}

class MeoofEventManager extends HTMLElement {
  setConfig(config) { this.config = config || {}; }
  set hass(value) {
    this._hass = value;
    if (!this._loaded) { this._loaded = true; this.period = 'month'; this.refresh(); }
    else if (!this._refreshing && Date.now() - (this._lastRefresh || 0) > 15000) this.refresh(true);
  }
  getCardSize() { return 8; }
  esc(value) { return String(value ?? "").replace(/[&<>\"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
  async refresh(silent = false) {
    this._refreshing = true;
    if (!silent) this.innerHTML = `<ha-card><div class="loading">正在读取猫咪图库与进食记录…</div></ha-card>`;
    try { this.data = await this._hass.callApi("GET", "meoof/manage"); this._lastRefresh = Date.now(); this.render(); }
    catch (err) { this.innerHTML = `<ha-card><div class="error">加载失败：${this.esc(err.message || err)}</div></ha-card>`; }
    finally { this._refreshing = false; }
  }
  async action(body, message) {
    if (message && !confirm(message)) return;
    try { await this._hass.callApi("POST", "meoof/manage", body); await this.refresh(); }
    catch (err) { alert(`操作失败：${err.message || err}`); }
  }
  render() {
    const cats = Object.keys(this.data.profiles || {});
    const options = cats.map(x => `<option value="${this.esc(x)}">${this.esc(x)}</option>`).join("");
    const allEvents = this.data.events || [];
    const now = new Date(), todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const weekStart = new Date(todayStart); weekStart.setDate(todayStart.getDate() - ((todayStart.getDay() + 6) % 7));
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
    const starts = {today:todayStart, week:weekStart, month:monthStart};
    const filtered = p => p === 'all' ? allEvents : allEvents.filter(e => new Date(e.time) >= starts[p]);
    this.visibleEvents = filtered(this.period);
    const periodBar = ['today','week','month','all'].map(p => `<button data-period="${p}" class="period ${this.period===p?'active':''}">${{today:'今天',week:'本周',month:'本月',all:'全部'}[p]} <b>${filtered(p).length}</b></button>`).join('');
    const events = this.visibleEvents.map((e, i) => `<div class="event">
      <img src="${this.esc(e.image_url)}" loading="lazy">
      <div class="event-main"><div><b>${this.esc(new Date(e.time).toLocaleString())}</b></div>
      <div class="current">当前分类：<b>${this.esc(e.cat)}</b></div>
      <div class="duration">录像覆盖：<b>${e.clip_duration ? `${Math.floor(e.clip_duration/60)}分${e.clip_duration%60}秒` : "暂无"}</b></div>
      <div class="controls"><select data-event-cat="${i}">${options}</select>
      <label><input type="checkbox" data-learn="${i}"> 加入识别图库</label></div>
      <div class="buttons"><button data-fix="${i}">修正分类</button><button class="danger" data-del-event="${i}">删除记录</button></div></div>
    </div>`).join("") || `<div class="empty">暂无进食记录</div>`;
    const galleries = cats.map(cat => `<section><h3>${this.esc(cat)} · ${(this.data.profiles[cat] || []).length} 张</h3>
      <div class="gallery">${(this.data.profiles[cat] || []).map(sample => `<div class="sample">
        <img src="${this.esc(sample.image_url)}" loading="lazy">
        <button class="danger" data-del-sample="${this.esc(cat)}|${this.esc(sample.filename)}">删除</button>
      </div>`).join("")}</div></section>`).join("");
    this.innerHTML = `<ha-card><style>
      ha-card{padding:16px}.tabs{display:flex;gap:8px;margin-bottom:14px}.tabs button.active{background:var(--primary-color);color:white}
      button,select,input{font:inherit;padding:7px 10px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}
      .danger{color:var(--error-color)}.periods{display:flex;gap:8px;align-items:center;margin:0 0 10px;flex-wrap:wrap}.period{border:0;background:var(--secondary-background-color)}.period.active{background:var(--primary-color);color:var(--text-primary-color)}.period b{margin-left:3px}.refresh{margin-left:auto}.event{display:grid;grid-template-columns:140px 1fr;gap:14px;padding:12px 0;border-bottom:1px solid var(--divider-color)}
      .event img{width:140px;height:94px;object-fit:cover;border-radius:10px}.current{margin-top:7px}.duration{margin:3px 0 7px;color:var(--secondary-text-color)}.controls,.buttons{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.buttons{margin-top:8px}
      .gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:12px}.sample img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:10px}.sample button{width:100%;margin-top:5px}
      .upload{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 20px}.hidden{display:none}.loading,.error,.empty{padding:20px}.error{color:var(--error-color)}
      @media(max-width:600px){.event{grid-template-columns:105px 1fr}.event img{width:105px;height:80px}}
    </style>
    <div class="tabs"><button data-tab="events" class="active">进食记录纠错</button><button data-tab="profiles">猫咪图库</button></div>
    <div data-pane="events"><div class="periods">${periodBar}<button class="refresh" data-refresh>刷新</button></div>${events}</div>
    <div data-pane="profiles" class="hidden"><h2>上传档案图片</h2><div class="upload"><input data-new-cat placeholder="猫咪名称"><input data-upload type="file" accept="image/jpeg,image/png,image/webp"><button data-upload-btn>上传</button></div>${galleries}</div>
    </ha-card>`;
    this.bind();
  }
  bind() {
    this.querySelectorAll("[data-event-cat]").forEach(select => {
      select.value = this.data.events[Number(select.dataset.eventCat)].cat;
    });
    this.querySelectorAll("[data-tab]").forEach(btn => btn.onclick = () => {
      this.querySelectorAll("[data-tab]").forEach(x => x.classList.toggle("active", x === btn));
      this.querySelectorAll("[data-pane]").forEach(x => x.classList.toggle("hidden", x.dataset.pane !== btn.dataset.tab));
    });
    this.querySelectorAll("[data-period]").forEach(btn => btn.onclick = () => { this.period = btn.dataset.period; this.render(); });
    this.querySelector("[data-refresh]").onclick = () => this.refresh();
    this.querySelectorAll("[data-fix]").forEach(btn => btn.onclick = () => {
      const i = Number(btn.dataset.fix), event = this.visibleEvents[i];
      const cat = this.querySelector(`[data-event-cat="${i}"]`).value;
      const learn = this.querySelector(`[data-learn="${i}"]`).checked;
      this.action({action:"reclassify", snapshot:event.snapshot, cat, learn}, `把这条记录从“${event.cat}”改为“${cat}”吗？`);
    });
    this.querySelectorAll("[data-del-event]").forEach(btn => btn.onclick = () => {
      const event = this.visibleEvents[Number(btn.dataset.delEvent)];
      this.action({action:"delete_event", snapshot:event.snapshot}, "确定删除这条进食记录及其截图吗？此操作无法撤销。");
    });
    this.querySelectorAll("[data-del-sample]").forEach(btn => btn.onclick = () => {
      const [cat, filename] = btn.dataset.delSample.split("|");
      this.action({action:"delete_sample", cat, filename}, `确定从“${cat}”图库删除这张样本吗？`);
    });
    this.querySelector("[data-upload-btn]").onclick = async () => {
      const cat = this.querySelector("[data-new-cat]").value.trim(), file = this.querySelector("[data-upload]").files[0];
      if (!cat || !file) return alert("请填写猫咪名称并选择图片");
      const image = await new Promise((resolve, reject) => { const r = new FileReader(); r.onload=()=>resolve(r.result); r.onerror=reject; r.readAsDataURL(file); });
      await this.action({action:"upload_sample", cat, image});
    };
  }
}
customElements.define("meoof-event-manager", MeoofEventManager);
window.customCards = window.customCards || [];
window.customCards.push({type:"meoof-event-manager", name:"觅凹进食与猫咪图库管理"});

class MeoofCatSummary extends HTMLElement {
  setConfig(config) {
    this.config = config || {};
    if (!['eating', 'litter'].includes(this.config.mode)) throw new Error('mode must be eating or litter');
  }
  set hass(value) { this._hass = value; this.render(); }
  getCardSize() { return 3; }
  esc(value) { return String(value ?? "").replace(/[&<>\"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
  formatDuration(seconds) {
    seconds = Number(seconds || 0);
    return seconds >= 60 ? `${Math.floor(seconds / 60)}分${seconds % 60}秒` : `${seconds}秒`;
  }
  render() {
    if (!this._hass || !this.config) return;
    const isEating = this.config.mode === 'eating';
    const source = meoofEntityByRole(this._hass, isEating ? 'eating_day' : 'litter_history', this.config.entity);
    const attrs = source?.attributes || {};
    const profiles = meoofEntityByRole(this._hass, 'cat_profiles', this.config.profiles_entity);
    const avatars = profiles?.attributes?.avatars || {};
    const names = [...new Set([
      ...Object.keys(avatars),
      ...Object.keys(isEating ? (attrs.by_cat || {}) : (attrs.latest_by_cat || {})),
    ])].slice(0, 6);
    const cats = names.map(name => ({name, avatar:avatars[name] || ''}));
    const cards = cats.map(cat => {
      const avatar = cat.avatar;
      let main, sub, badge = '';
      if (isEating) {
        const count = Number((attrs.by_cat || {})[cat.name] || 0);
        const seconds = Number((attrs.duration_by_cat || {})[cat.name] || 0);
        main = `${count}<span>次</span>`;
        sub = `约 ${this.formatDuration(seconds)}`;
      } else {
        const item = (attrs.latest_by_cat || {})[cat.name];
        if (item) {
          const date = new Date(item.time);
          main = `${date.getMonth()+1}月${date.getDate()}日`;
          sub = `${date.toLocaleTimeString('zh-CN',{hour12:false})} · ${item.duration}秒${item.weight != null ? ` · ${item.weight}kg` : ''}`;
          badge = item.inferred ? '<span class="badge">体重推断</span>' : '';
        } else { main = '暂无'; sub = '还没有如厕记录'; }
      }
      return `<div class="cat-card">
        <div class="avatar-wrap">${avatar ? `<img src="${this.esc(avatar)}">` : '<div class="avatar-fallback">🐈</div>'}</div>
        <div class="cat-name">${cat.name}</div>
        <div class="main-value">${main}</div>
        <div class="sub-value">${sub}</div>${badge}
      </div>`;
    }).join('');
    const total = Number(source?.state || 0);
    this.innerHTML = `<ha-card><style>
      ha-card{padding:18px;background:var(--ha-card-background,var(--card-background-color));overflow:hidden}
      .top{display:flex;justify-content:space-between;align-items:baseline;margin:0 2px 16px}.title{font-size:20px;font-weight:650;letter-spacing:-.3px}.total{font-size:13px;color:var(--secondary-text-color)}
      .cats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.cat-card{position:relative;text-align:center;padding:16px 8px 14px;border-radius:18px;background:var(--secondary-background-color);min-width:0}
      .avatar-wrap{width:58px;height:58px;margin:0 auto 9px}.avatar-wrap img,.avatar-fallback{width:58px;height:58px;border-radius:50%;object-fit:cover;display:flex;align-items:center;justify-content:center;background:var(--card-background-color);font-size:34px;box-shadow:0 2px 10px rgba(0,0,0,.10)}
      .cat-name{font-size:15px;font-weight:650;margin-bottom:5px}.main-value{font-size:22px;font-weight:700;line-height:1.15;white-space:nowrap}.main-value span{font-size:12px;font-weight:500;margin-left:2px;color:var(--secondary-text-color)}
      .sub-value{font-size:12px;color:var(--secondary-text-color);margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.badge{display:inline-block;margin-top:7px;padding:2px 7px;border-radius:999px;background:color-mix(in srgb,var(--warning-color) 14%,transparent);color:var(--warning-color);font-size:10px}
      @media(max-width:430px){ha-card{padding:14px}.cats{gap:7px}.cat-card{padding:13px 4px 12px;border-radius:15px}.avatar-wrap,.avatar-wrap img,.avatar-fallback{width:48px;height:48px}.main-value{font-size:18px}.sub-value{font-size:11px}}
    </style><div class="top"><div class="title">${isEating ? '今日进食' : '最近如厕'}</div>${isEating ? `<div class="total">今日共 ${total} 次</div>` : '<div class="total">跨日保留</div>'}</div><div class="cats">${cards}</div></ha-card>`;
  }
}
customElements.define('meoof-cat-summary', MeoofCatSummary);
window.customCards.push({type:'meoof-cat-summary', name:'觅凹猫咪摘要卡'});

class MeoofFeedTimeline extends HTMLElement {
  setConfig(config) { this.config = config || {}; this.period = this.period || 'week'; }
  set hass(value) {
    this._hass = value;
    const entity = meoofEntityByRole(value, 'feed_history', this.config?.entity);
    const signature = `${entity?.state || ''}|${entity?.last_updated || ''}`;
    if (!this._rendered || signature !== this._signature) {
      this._signature = signature;
      this.render();
      this._rendered = true;
    }
  }
  getCardSize() { return 5; }
  formatDate(date) { return `${date.getMonth()+1}月${date.getDate()}日`; }
  render() {
    if (!this._hass) return;
    const previousScroll = this._resetScroll ? 0 : (this.querySelector('.timeline')?.scrollTop || 0);
    this._resetScroll = false;
    const entity = meoofEntityByRole(this._hass, 'feed_history', this.config?.entity);
    const all = entity?.attributes?.records || [];
    const now = new Date(), today = new Date(now.getFullYear(),now.getMonth(),now.getDate());
    const starts = {today, week:new Date(now.getTime()-7*86400000), month:new Date(now.getTime()-30*86400000)};
    const filtered = key => all.filter(item => new Date(item.time) >= starts[key]);
    const records = filtered(this.period);
    const buttons = [['today','今天'],['week','近7天'],['month','近30天']].map(([key,label]) => `<button data-feed-period="${key}" class="chip ${this.period===key?'active':''}">${label}<b>${filtered(key).length}</b></button>`).join('');
    let lastDay = '';
    const timeline = records.map(item => {
      const date = new Date(item.time), day = this.formatDate(date), showDay = day !== lastDay; lastDay = day;
      const portions = Number(item.actual_portions ?? item.left_actual_portions ?? 0);
      const mode = item.feed_mode || (item.feed_type_code === 2 ? '手动' : '计划');
      return `${showDay ? `<div class="day">${day}</div>` : ''}<div class="entry"><div class="rail"><i></i></div><div class="time">${date.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false})}</div><div class="mode ${mode==='手动'?'manual':''}">${mode}</div><div class="portions"><strong>${portions}</strong> 份</div></div>`;
    }).join('') || '<div class="empty">这个时间段暂无出粮记录</div>';
    this.innerHTML = `<ha-card><style>
      ha-card{padding:18px}.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.title{font-size:20px;font-weight:650}.chips{display:flex;gap:6px}.chip{border:0;border-radius:999px;padding:6px 10px;background:var(--secondary-background-color);color:var(--primary-text-color)}.chip b{margin-left:5px;font-size:11px}.chip.active{background:var(--primary-color);color:white}
      .timeline{max-height:390px;overflow:auto;padding-right:5px;scrollbar-width:thin}.day{font-size:12px;font-weight:650;color:var(--secondary-text-color);margin:12px 0 3px 23px}.entry{display:grid;grid-template-columns:20px 64px 52px 1fr;align-items:center;min-height:42px}.rail{height:100%;position:relative;border-left:2px solid var(--divider-color);margin-left:7px}.rail i{position:absolute;width:10px;height:10px;border-radius:50%;background:var(--primary-color);left:-6px;top:16px;box-shadow:0 0 0 4px var(--card-background-color)}.time{font-variant-numeric:tabular-nums;font-weight:600}.mode{justify-self:start;font-size:11px;padding:3px 8px;border-radius:999px;background:color-mix(in srgb,var(--primary-color) 12%,transparent);color:var(--primary-color)}.mode.manual{background:color-mix(in srgb,var(--warning-color) 14%,transparent);color:var(--warning-color)}.portions{text-align:right}.portions strong{font-size:19px}.empty{padding:22px 4px;color:var(--secondary-text-color);text-align:center}
      @media(max-width:430px){ha-card{padding:14px}.header{align-items:flex-start;gap:10px;flex-direction:column}.entry{grid-template-columns:20px 58px 48px 1fr}}
    </style><div class="header"><div class="title">出粮时间轴</div><div class="chips">${buttons}</div></div><div class="timeline">${timeline}</div></ha-card>`;
    const timelineElement = this.querySelector('.timeline');
    if (timelineElement) timelineElement.scrollTop = previousScroll;
    this.querySelectorAll('[data-feed-period]').forEach(btn => btn.onclick = () => { this.period=btn.dataset.feedPeriod; this._resetScroll=true; this.render(); });
  }
}
customElements.define('meoof-feed-timeline', MeoofFeedTimeline);
window.customCards.push({type:'meoof-feed-timeline', name:'觅凹出粮时间轴'});

class MeoofLatestEatingCard extends HTMLElement {
  setConfig(config) { this.config = config || {}; }
  set hass(value) { this._hass = value; this.render(); }
  getCardSize() { return 4; }
  esc(value) { return String(value ?? "").replace(/[&<>\"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
  render() {
    if (!this._hass) return;
    const camera = meoofEntityByRole(this._hass, 'latest_eating_camera', this.config.camera_entity);
    const latest = meoofEntityByRole(this._hass, 'latest_eating', this.config.entity);
    const picture = camera?.attributes?.entity_picture || '';
    const cat = latest?.attributes?.cat || '暂无记录';
    const rawTime = latest?.attributes?.time || latest?.attributes?.event_time;
    const time = rawTime ? new Date(rawTime).toLocaleString('zh-CN',{hour12:false}) : '';
    this.innerHTML = `<ha-card><style>
      ha-card{overflow:hidden}.photo{position:relative;aspect-ratio:16/10;background:var(--secondary-background-color)}.photo img{width:100%;height:100%;object-fit:cover;display:block}.empty{height:100%;display:flex;align-items:center;justify-content:center;color:var(--secondary-text-color)}
      .caption{display:flex;justify-content:space-between;align-items:center;padding:14px 16px}.cat{font-size:17px;font-weight:650}.time{font-size:12px;color:var(--secondary-text-color)}
    </style><div class="photo">${picture ? `<img src="${this.esc(picture)}">` : '<div class="empty">暂无进食截图</div>'}</div><div class="caption"><div class="cat">${this.esc(cat)}</div><div class="time">${this.esc(time)}</div></div></ha-card>`;
  }
}
customElements.define('meoof-latest-eating', MeoofLatestEatingCard);
window.customCards.push({type:'meoof-latest-eating', name:'觅凹最近进食'});

class MeoofSmartFeedCard extends HTMLElement {
  setConfig(config) { this.config = config || {}; }
  set hass(value) { this._hass = value; this.render(); }
  getCardSize() { return 6; }
  esc(value) { return String(value ?? '').replace(/[&<>\"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
  levelText(level) { return ({empty:'空',some:'少量',many:'较多'})[level] || '未知'; }
  statusText(status) {
    return ({suppressed:'已取消出粮',allowed:'正常出粮',error_allowed:'检查失败，正常出粮',checking:'检查中',test_only:'测试完成（未修改计划）',test_error:'测试失败（未修改计划）'})[status] || '暂无检查';
  }
  trend(records) {
    const values = {empty:0,some:1,many:2};
    const points = (records || []).filter(x => x.checked_at && x.food_level in values).slice(-24);
    if (!points.length) return '<div class="empty chart-empty">还没有余粮趋势数据</div>';
    const left=58,right=618,top=18,bottom=142;
    const coords = points.map((item,index) => {
      const x = points.length === 1 ? (left+right)/2 : left + index*(right-left)/(points.length-1);
      const y = bottom - values[item.food_level]*(bottom-top)/2;
      return {x,y,item};
    });
    const line = coords.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
    const dots = coords.map(p => `<circle cx="${p.x}" cy="${p.y}" r="5"><title>${this.esc(new Date(p.item.checked_at).toLocaleString('zh-CN',{hour12:false}))} · ${this.levelText(p.item.food_level)} · ${Math.round((p.item.confidence || 0)*100)}%</title></circle>`).join('');
    const first = new Date(points[0].checked_at).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});
    const last = new Date(points[points.length-1].checked_at).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});
    return `<div class="chart-title"><b>碗内余粮趋势</b><span>最近 ${points.length} 次检查</span></div><svg class="trend" viewBox="0 0 640 178" role="img" aria-label="碗内余粮趋势折线图">
      <line x1="${left}" y1="${top}" x2="${right}" y2="${top}"/><line x1="${left}" y1="${(top+bottom)/2}" x2="${right}" y2="${(top+bottom)/2}"/><line x1="${left}" y1="${bottom}" x2="${right}" y2="${bottom}"/>
      <text x="4" y="${top+5}">较多</text><text x="4" y="${(top+bottom)/2+5}">少量</text><text x="4" y="${bottom+5}">空</text>
      <polyline points="${line}"/>${dots}<text class="time" x="${left}" y="170">${this.esc(first)}</text><text class="time end" x="${right}" y="170">${this.esc(last)}</text>
    </svg>`;
  }
  async runTest(entityId) {
    if (!entityId || this._testing) return;
    this._testing = true;
    this.render();
    try { await this._hass.callService('button','press',{entity_id:entityId}); }
    finally { this._testing = false; this.render(); }
  }
  render() {
    if (!this._hass) return;
    const plan = meoofEntityByRole(this._hass, 'today_feed_plan', this.config?.plan_entity);
    const smart = meoofEntityByRole(this._hass, 'smart_feed', this.config?.entity);
    const items = (plan?.attributes?.items || []).filter(x => x.enabled);
    const now = new Date();
    const upcoming = items.map(item => {
      const date = new Date(now); date.setHours(item.hour,item.minute,0,0);
      return {...item,date};
    }).filter(x => x.date >= now).sort((a,b) => a.date-b.date);
    const latest = smart?.attributes?.latest || {};
    const records = smart?.attributes?.records || [];
    const enabled = Boolean(smart?.attributes?.enabled);
    const testEntity = this.config?.test_entity || Object.entries(this._hass.states).find(([id,state]) => id.startsWith('button.') && String(state.attributes?.friendly_name || '').includes('测试余粮识别'))?.[0];
    const rows = upcoming.map((item,index) => `<div class="plan-row ${index===0?'next':''}">
      <div class="dot"></div><div><b>${String(item.hour).padStart(2,'0')}:${String(item.minute).padStart(2,'0')}</b><small>${item.left + item.right} 份${index===0 && enabled?' · 将提前检查':''}</small></div>
      <span>${index===0?'下一次':'计划'}</span></div>`).join('') || '<div class="empty">今天没有待执行的出粮计划</div>';
    const snapshot = latest.snapshot ? `<img src="${this.esc(latest.snapshot)}">` : '';
    const detail = latest.checked_at ? `<div class="latest">${snapshot}<div><div class="level ${latest.food_level || ''}">${this.levelText(latest.food_level)}</div><b>${this.statusText(latest.status)}</b><small>${new Date(latest.checked_at).toLocaleString('zh-CN',{hour12:false})}${latest.confidence != null ? ` · 置信度 ${Math.round(latest.confidence*100)}%` : ''}</small><p>${this.esc(latest.reason || latest.error || '')}</p></div></div>` : '<div class="empty latest-empty">还没有执行过余粮检查</div>';
    const testButton = testEntity ? `<button class="test" ${this._testing?'disabled':''}>${this._testing?'正在拍照识别…':'立即安全检测（不出粮）'}</button>` : '';
    this.innerHTML = `<ha-card><style>
      ha-card{padding:18px}.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.title{font-size:20px;font-weight:650}.state{font-size:12px;padding:5px 10px;border-radius:999px;background:var(--secondary-background-color)}.state.on{color:var(--success-color);background:color-mix(in srgb,var(--success-color) 12%,transparent)}
      .plan-row{display:grid;grid-template-columns:18px 1fr auto;align-items:center;padding:10px 8px;border-radius:12px}.plan-row.next{background:var(--secondary-background-color)}.dot{width:9px;height:9px;border-radius:50%;background:var(--divider-color)}.next .dot{background:var(--primary-color);box-shadow:0 0 0 4px color-mix(in srgb,var(--primary-color) 15%,transparent)}.plan-row b{display:block;font-size:16px}.plan-row small,.latest small{display:block;color:var(--secondary-text-color);margin-top:2px}.plan-row span{font-size:11px;color:var(--secondary-text-color)}
      .divider{height:1px;background:var(--divider-color);margin:14px 0}.latest{display:grid;grid-template-columns:112px 1fr;gap:14px;align-items:center}.latest img{width:112px;height:84px;object-fit:cover;border-radius:12px}.latest p{font-size:12px;color:var(--secondary-text-color);margin:5px 0 0}.level{float:right;font-size:14px;font-weight:700;padding:5px 10px;border-radius:999px;background:var(--secondary-background-color)}.level.empty{color:var(--success-color)}.level.some{color:var(--warning-color)}.level.many{color:var(--error-color)}.empty{padding:16px;text-align:center;color:var(--secondary-text-color)}.latest-empty{padding:8px}.chart-title{display:flex;justify-content:space-between;align-items:center;margin:16px 0 4px}.chart-title span{font-size:11px;color:var(--secondary-text-color)}.trend{display:block;width:100%;height:auto;max-height:190px}.trend line{stroke:var(--divider-color);stroke-width:1}.trend polyline{fill:none;stroke:var(--primary-color);stroke-width:4;stroke-linecap:round;stroke-linejoin:round}.trend circle{fill:var(--card-background-color);stroke:var(--primary-color);stroke-width:4}.trend text{fill:var(--secondary-text-color);font-size:12px}.trend .time{font-size:10px}.trend .end{text-anchor:end}.test{width:100%;margin-top:10px;padding:10px;border:0;border-radius:10px;background:var(--secondary-background-color);color:var(--primary-text-color);font-weight:600;cursor:pointer}.test:disabled{opacity:.6;cursor:wait}.chart-empty{padding:28px 8px}
      @media(max-width:430px){.latest{grid-template-columns:88px 1fr}.latest img{width:88px;height:72px}.trend text{font-size:11px}}
    </style><div class="head"><div class="title">智能出粮守护</div><div class="state ${enabled?'on':''}">${enabled?'已启用':'未启用'}</div></div><div>${rows}</div><div class="divider"></div>${detail}${testButton}${this.trend(records)}</ha-card>`;
    this.querySelector('.test')?.addEventListener('click', () => this.runTest(testEntity));
  }
}
customElements.define('meoof-smart-feed', MeoofSmartFeedCard);
window.customCards.push({type:'meoof-smart-feed', name:'觅凹智能出粮守护'});
