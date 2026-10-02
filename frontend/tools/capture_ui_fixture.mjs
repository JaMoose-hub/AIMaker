// Static-render fixtures only. Real timer and scroll lifecycle tests are separate.
export const passiveCountdown=()=>({remaining:null,run:action=>action(),cancel(){}});
export const passiveChat=()=>({chatRef:{current:null},contentRef:{current:null},unread:false,onScroll(){},showLatest(){},followNext(){}});
