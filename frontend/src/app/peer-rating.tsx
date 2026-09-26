"use client";
import {useEffect,useState} from 'react';
import type {PeerFeedbackState} from '@/lib/contracts';
import {useT} from '@/i18n/context';
import styles from './social.module.css';
export default function PeerRating({state,busy,onSave}:{state:PeerFeedbackState;busy:boolean;onSave:(rating:number,comment:string)=>void}){
 const t=useT();const selected=state.feedback?.star_rating??0;const [hover,setHover]=useState(0),[comment,setComment]=useState(state.feedback?.comment??'');
 useEffect(()=>{setComment(state.feedback?.comment??'');},[state.feedback?.comment]);
 const enabled=state.available&&!busy;
 return <section><h2>{t('Peer feedback')}</h2><p>{t('How well did your partner handle this conversation?')}</p><p>{t('Your feedback for:')} {state.peer_name}</p>
 <div role="radiogroup" aria-label={t('Peer rating')} className={styles.stars} onMouseLeave={()=>setHover(0)}>{[1,2,3,4,5].map(n=><button type="button" role="radio" aria-checked={selected===n} aria-label={t('{0} out of 5 stars',n)} key={n} disabled={!enabled} tabIndex={n===(Math.ceil(selected)||1)?0:-1} onMouseEnter={()=>setHover(n)} onFocus={()=>setHover(n)} onBlur={()=>setHover(0)} onClick={()=>onSave(n,comment)} onKeyDown={e=>{const target=e.key==='ArrowRight'||e.key==='ArrowDown'?Math.min(5,n+1):e.key==='ArrowLeft'||e.key==='ArrowUp'?Math.max(1,n-1):e.key==='Home'?1:e.key==='End'?5:0;if(target){e.preventDefault();const buttons=e.currentTarget.parentElement!.querySelectorAll('button');(buttons[target-1] as HTMLButtonElement).focus();onSave(target,comment);}}}><svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true" fill={n<=(hover||selected)?'currentColor':'none'} stroke="currentColor" strokeWidth="1.4"><path d="m12 2 3 6.2 6.8 1-4.9 4.8 1.2 6.8-6.1-3.2-6.1 3.2 1.2-6.8L2.2 9.2 9 8.2Z"/></svg></button>)}</div>
 <p role="status">{selected?t('{0} stars — {1} points',selected,state.feedback?.score_points??0):t('Select rating')}</p>
 {!state.available&&<p>{t(state.reason??'')}</p>}
 <label>{t('Private comment')}<textarea value={comment} onChange={e=>setComment(e.target.value)} disabled={!state.available}/></label><button disabled={!enabled||!selected||comment===(state.feedback?.comment??'')} onClick={()=>onSave(selected,comment)}>{t('Save comment')}</button>
 </section>;
}
