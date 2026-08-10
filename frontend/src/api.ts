export const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'
export type Novel = { id:number; title:string; genre?:string; theme?:string; target_words?:number; default_style?:string; master_outline?:string }
export type Chapter = { id:number; novel_id:number; sequence:number; title:string; outline:string; content:string; writing_requirements:string; target_words?:number; actual_words:number; status:string }
export type Character = { id:number; name:string; profile:string; current_status:string; confirmed:boolean; goal:string; personality:string; relationships:string; is_main_character:boolean; importance:number; current_location:string; current_goal:string; current_emotion_or_state:string; arc_or_growth:string; status:string }
export type Fact = { id:number; fact_type:string; content:string; status:string; source_chapter_id?:number }
export type Timeline = { id:number; time_description:string; location:string; content:string; participants:string; confirmed:boolean }

export async function request<T>(path:string, options:RequestInit = {}):Promise<T> {
  const r = await fetch(`${API}${path}`, { headers:{'Content-Type':'application/json', ...(options.headers || {})}, ...options })
  if (!r.ok) { const body = await r.json().catch(()=>null); throw new Error(body?.detail || `请求失败 (${r.status})`) }
  return r.status === 204 ? undefined as T : r.json()
}
export const json = (method:string, body?:unknown):RequestInit => ({method, body: body === undefined ? undefined : JSON.stringify(body)})

export async function streamChapter(path:string, payload:unknown, onDelta:(x:string)=>void) {
  const r = await fetch(`${API}${path}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)})
  if (!r.ok) { const d=await r.json().catch(()=>null); throw new Error(d?.detail || '生成请求失败') }
  const reader = r.body?.getReader(); if (!reader) throw new Error('浏览器不支持流式响应')
  const decoder = new TextDecoder(); let buffer=''
  while (true) { const {value,done}=await reader.read(); buffer += decoder.decode(value || new Uint8Array(), {stream:!done}); const events=buffer.split('\n\n'); buffer=events.pop() || ''
    for (const event of events) { const line=event.split('\n').find(x=>x.startsWith('data: ')); if (!line) continue; const data=JSON.parse(line.slice(6)); if(data.type==='delta') onDelta(data.text); if(data.type==='error') throw new Error(data.message) }
    if(done) break
  }
}

export type AgentEvent = {run_id:string;event_type:'status'|'content_delta'|'tool'|'context'|'token'|'warning'|'result'|'error'|'done';timestamp:string;data:any}
export async function streamAgentRun(path:string, payload:unknown, onEvent:(event:AgentEvent)=>void, signal?:AbortSignal) {
  const r=await fetch(`${API}${path}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal})
  if(!r.ok){const d=await r.json().catch(()=>null);throw new Error(d?.detail||'Agent 运行请求失败')}
  const reader=r.body?.getReader();if(!reader)throw new Error('浏览器不支持流式响应')
  const decoder=new TextDecoder();let buffer=''
  while(true){const {value,done}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});const blocks=buffer.split('\n\n');buffer=blocks.pop()||'';for(const block of blocks){const line=block.split('\n').find(x=>x.startsWith('data: '));if(line)onEvent(JSON.parse(line.slice(6)))}if(done)break}
}
