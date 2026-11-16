import React from 'react';
import{createRoot}from'react-dom/client';
import{CoachGuide}from'../src/components/learning/CoachGuide';
import{LessonWorkshop}from'../src/components/learning/LessonWorkshop';
import lessons from '../../api/routes/learning_course_content.json';
import '../src/components/learning/portal.css';
const workshop=lessons.find(l=>l.workshop?.visual?.title==='Trace the sequence, then the challenge')!.workshop;
createRoot(document.getElementById('root')!).render(<CoachGuide><h1>Higher highs and higher lows</h1><LessonWorkshop workshop={workshop as any} onReview={()=>{}}/></CoachGuide>);
