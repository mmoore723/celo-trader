export function limitedAccess(user:{is_admin?:boolean;access_profile?:string}|null){return !user?.is_admin && !!user?.access_profile && !['legacy','trading'].includes(user.access_profile);}
export function learningAccess(profile?:string){return ['learning','learning_discord'].includes(profile??'');}
export function visibleTab(path:string,user:{is_admin?:boolean;access_profile?:string}|null){if(path==='/admin')return !!user?.is_admin;if(!limitedAccess(user))return true;return path==='/trading'||(path==='/playbooks'&&learningAccess(user?.access_profile));}
