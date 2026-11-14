export function guideSeen(user:string){try{return localStorage.getItem(`celo_tour_v1_${user}`)==='1';}catch{return false;}}
