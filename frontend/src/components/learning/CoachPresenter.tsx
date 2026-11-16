import './presenter.css';

// Approved introduction only. Local media, no generation service or trading API.
export function CoachPresenter(){
 return <aside className="coach-presenter" aria-label="Coach Celo video introduction">
  <div><strong>Meet Coach Celo</strong><p>Your guide through the Learning Portal.</p></div>
  <video controls playsInline preload="none" poster="/assets/coach/coach-celo-desk.jpg" aria-label="Play Coach Celo’s introduction">
   <source src="/assets/coach/coach-celo-introduction.mp4" type="video/mp4"/>
   <track kind="captions" src="/assets/coach/coach-celo-introduction.vtt" srcLang="en" label="English" default/>
   Your browser does not support video playback.
  </video>
 </aside>;
}
