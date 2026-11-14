import {useEffect,useState} from 'react';
import {useAuth} from '../contexts/AuthContext';
export function RunAsBanner(){
 const {user}=useAuth();const [error,setError]=useState('');
 useEffect(()=>{const session=user?.support_session;if(!session || session.expired)return;const timer=setTimeout(()=>window.location.reload(),Math.max(0,session.expires_at*1000-Date.now()));return ()=>clearTimeout(timer);},[user?.support_session]);
 if(!user?.support_session)return null;
 async function stop(){try{const r=await fetch('/api/auth/run-as/stop',{method:'POST',credentials:'include'});if(!r.ok)throw new Error('Could not return to Admin. Please try again.');localStorage.setItem('celo-account-switch',String(Date.now()));window.location.hash='/admin';window.location.reload();}catch(e){setError((e as Error).message);}}
 return <aside role="status" style={{background:'var(--surface-raised)',border:'2px solid var(--warning)',padding:12,marginBottom:12}}><strong>{user.support_session.expired ? "Run as user ended. Return to Admin to continue." : `Running as ${user.name}`}</strong><span> · Admin: {user.support_session.actor_name}. Actions affect this user’s account.</span><button className="btn btn-primary ml-3" onClick={stop}>Return to Admin</button>{error&&<p role="alert">{error}</p>}</aside>;
}
