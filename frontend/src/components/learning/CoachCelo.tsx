import coach from '../../assets/learning/coach-celo-pointing.png';
import './coach.css';
export function CoachCelo({children}:{children:React.ReactNode}){return <aside className="coach-celo"><img src={coach} alt="Coach Celo pointing toward the lesson"/><div><strong>Coach Celo</strong><div>{children}</div></div></aside>}
