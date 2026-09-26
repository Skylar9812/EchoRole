"use client";
import {createContext, useContext, useState, useEffect, type ReactNode} from 'react';
import type {Language} from '@/lib/contracts';
import cn from './zh-CN.json';
import tw from './zh-TW.json';
const dictionaries: Record<string, Record<string,string>> = {'zh-CN': cn, 'zh-TW': tw};
const Context = createContext({language:'en' as Language, preferred:'en' as Language, setPreferred: (_:Language)=>{}, setRoomLanguage: (_:Language|null)=>{}});
export function I18nProvider({children}:{children:ReactNode}) {
 const [preferred,setPreferredState]=useState<Language>('en');
 const [roomLanguage,setRoomLanguage]=useState<Language|null>(null);
 useEffect(()=>{const saved=localStorage.getItem('echorole-language'); if(saved==='en'||saved==='zh-CN'||saved==='zh-TW')setPreferredState(saved);},[]);
 const language=roomLanguage??preferred;
 useEffect(()=>{document.documentElement.lang=language;},[language]);
 function setPreferred(value:Language){setPreferredState(value);localStorage.setItem('echorole-language',value);}
 return <Context.Provider value={{language,preferred,setPreferred,setRoomLanguage}}>{children}</Context.Provider>;
}
export const useI18n=()=>useContext(Context);
export function useT(){const {language}=useI18n();return (key:string,...values:(string|number)[])=>{const value=dictionaries[language]?.[key]??key;return value.replace(/\{(\d+)\}/g,(_,index)=>String(values[Number(index)]??''));};}
export function LanguageSelector(){const {language,setPreferred}=useI18n();return <div role="group" aria-label="Language" className="language-selector">{(['en','zh-CN','zh-TW'] as Language[]).map((value,index)=><button type="button" key={value} lang={value} aria-pressed={language===value} onClick={()=>setPreferred(value)}>{['EN','简中','繁中'][index]}</button>)}</div>;}

export function useErrorText(){const {language}=useI18n();const t=useT();return (message:string)=>{
  if(language==='en') return message;
  const translated=dictionaries[language]?.[message];
  if(translated) return translated;
  // Validation replies are deliberately written by the server in the room's
  // language (for example, the explanation that an action is too short).
  // Preserve those actionable messages instead of masking them with a generic
  // transport error simply because they are dynamic rather than dictionary keys.
  if(/[\u3400-\u9fff]/.test(message)) return message;
  return t('Request could not be completed. Refresh status and retry the original request.');
};}
