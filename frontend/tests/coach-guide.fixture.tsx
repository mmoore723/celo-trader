import React from 'react';
import{createRoot}from'react-dom/client';
import{CoachGuide}from'../src/components/learning/CoachGuide';
import{LessonWorkshop}from'../src/components/learning/LessonWorkshop';
import lessons from '../../api/routes/learning_course_content.json';
import '../src/components/learning/portal.css';
const fullWorkshop=lessons.find(l=>l.workshop?.visual?.title==='Trace the sequence, then the challenge')!.workshop;
const workshop=location.search.includes('short')?{goal:'Playback lifecycle test',steps:[{title:'First section',explain:'Read the first candle.',example:'A completed close.'},{title:'Second section',explain:'Now read the next section.',example:'Practice comes next.'}],mistake:'Wait for completed candles.',challenge:{prompt:'Choose for yourself',choices:['Above','Below'],correct:0,explanation:'Answer stays hidden until you ask.'},visual:{kind:'candles',title:'Playback test',bars:[{open:10,high:12,low:9,close:11}],labels:['Bar 1'],level:null,caption:'Test only',notes:['The close is above the open.']}}:fullWorkshop;
createRoot(document.getElementById('root')!).render(<CoachGuide><h1>Higher highs and higher lows</h1><LessonWorkshop workshop={workshop as any} onReview={()=>{}}/></CoachGuide>);
