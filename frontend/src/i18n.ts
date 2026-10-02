// UI language. Cantonese source strings are the keys; a missing English entry falls back to the Cantonese text.
export type Lang = 'zh-HK' | 'en';

const STORAGE_KEY = 'stillhere_lang';

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'en' || saved === 'zh-HK') return saved;
  } catch {}
  const browser = (navigator.language || '').toLowerCase();
  // Many Hong Kong phones run in English, so en-HK still starts in Cantonese.
  return browser.startsWith('en') && browser !== 'en-hk' ? 'en' : 'zh-HK';
}

let current: Lang = initialLang();
document.documentElement.lang = current;

export function getLang(): Lang { return current; }

export function setLang(lang: Lang) {
  current = lang;
  document.documentElement.lang = lang;
  try { localStorage.setItem(STORAGE_KEY, lang); } catch {}
}

export function t(key: string, ...args: (string | number)[]): string {
  const template = current === 'en' ? EN[key] ?? key : key;
  return template.replace(/\{(\d+)\}/g, (_, index) => String(args[Number(index)] ?? ''));
}

// Backend errors carry a code; show English text for the ones the app can hit.
export function translateError(code: string | undefined, message: string): string {
  return current === 'en' && code && ERRORS_EN[code] ? ERRORS_EN[code] : message;
}

const ERRORS_EN: Record<string, string> = {
  INVALID_SIGNUP: 'Username needs at least 3 characters and password at least 8.',
  USERNAME_TAKEN: 'That username is already taken.',
  INVALID_LOGIN: 'Incorrect username or password.',
  CONFIRMATION_REQUIRED: 'You must confirm that you are 18 or older.',
  INVALID_MESSAGE: 'A message cannot be empty or longer than 8,000 characters.',
  MODEL_UNAVAILABLE: 'The reply took too long. Please try again.',
  INVALID_SEARCH: 'Enter a person, place, year or story to search for.',
  NO_ANSWERS: 'Please answer at least one question.',
};

const EN: Record<string, string> = {
  // Landing and sign-in
  '仍在 · 家族相簿': 'StillHere · Family Album',
  '將屋企人嘅舊相同故事，好好留低。': 'Keep your family\'s old photos and the stories behind them.',
  '上載舊相，AI 會一條一條問你：相入面係邊個、嗰日發生咩事。你講，佢幫你整理。之後講一句就搵得返。': 'Upload old photos and the AI asks, one question at a time: who is in the picture, what happened that day. You tell it; it writes it up. Later, one sentence finds the photo again.',
  '開始使用': 'Get started',
  '已有帳戶？登入': 'Have an account? Sign in',
  '功能': 'Features',
  'AI 問，你答': 'The AI asks, you answer',
  'AI 睇完相會問人物、場合同時間。唔記得可以跳過，保存之前你可以改。': 'After looking at a photo, the AI asks about the people, the occasion and the date. Skip anything you can\'t remember, and edit before you save.',
  '講一句就搵到': 'Find a photo with one sentence',
  '例如「考完會考飲茶嗰張」、「2019 長洲」，AI 會喺你嘅相簿入面搵。': 'Try "the dim sum after my exams" or "Cheung Chau 2019" and the AI searches your album.',
  '冇網都睇得到': 'Works without internet',
  '加到手機主畫面之後，喺飛機上都可以睇相同故事。': 'Add it to your home screen and you can read photos and stories on a plane.',
  '點樣冇網都睇得到': 'How to use it offline',
  '將呢個網頁加到手機主畫面，佢就會好似 app 咁，喺飛機上或者冇網嘅地方都睇到相同故事。': 'Add this page to your phone\'s home screen and it works like an app, so you can see photos and stories on a plane or anywhere without a connection.',
  '撳底部嘅「分享」掣': 'Tap the Share button at the bottom',
  '揀「加至主畫面」': 'Choose "Add to Home Screen"',
  '撳「新增」': 'Tap "Add"',
  '撳右上角「⋮」': 'Tap "⋮" at the top right',
  '揀「安裝應用程式」或者「加到主畫面」': 'Choose "Install app" or "Add to Home screen"',
  '第一次要有網打開相簿，相片先會存落手機。冇網嘅時候可以睇相、睇故事、用文字搵相；講回憶、AI 整理同上載相片要等有網。': 'Open the album once while online so the photos are saved to your phone. Offline you can view photos, read stories and search by text; reminiscing with the AI, AI write-ups and uploads need a connection.',
  '你嘅相片': 'Your photos',
  '相片同故事只屬於你嘅帳戶，其他用戶睇唔到。AI 喺我哋自己嘅伺服器運行，唔會交俾其他 AI 公司。': 'Photos and stories belong to your account only; other users cannot see them. The AI runs on our own servers and nothing is passed to other AI companies.',
  'AI 整理嘅內容可能有錯，保存前請你自己睇一次。': 'What the AI writes can be wrong, so please read it before you save.',
  '開始整理第一本相簿': 'Start your first album',
  '返嚟喇。': 'Welcome back.',
  '建立私人空間': 'Create your private space',
  '每個帳戶最多可以整理 5 本相簿。相片同故事只屬於你嘅帳戶。': 'Each account can keep up to 5 albums. Photos and stories belong to your account only.',
  '用戶名稱': 'Username',
  '密碼': 'Password',
  '請稍等…': 'Please wait…',
  '登入': 'Sign in',
  '建立帳戶': 'Create account',
  '第一次使用？建立帳戶': 'New here? Create an account',
  '‹ 返回介紹': '‹ Back to introduction',
  'AI 喺我哋自己嘅伺服器運行': 'The AI runs on our own servers',
  '登入失敗': 'Could not sign in',
  '正在準備私人空間…': 'Getting your private space ready…',

  // Creating an album
  '你想為邊個整理回憶？': 'Whose memories would you like to keep?',
  '相片同故事只屬於你。建立之後就可以揀相。': 'Photos and stories are yours alone. You can add photos right after this.',
  ' 你而家有 {0}／5 本相簿。': ' You have {0} of 5 albums.',
  '佢嘅名或者稱呼': 'Their name, or what you call them',
  '例如：婆婆': 'e.g. Grandma',
  '佢係你嘅': 'They are your',
  '例如：外婆、阿媽、屋企隻狗': 'e.g. grandmother, mum, family dog',
  '有冇想 AI 先知道嘅背景？（選填）': 'Anything the AI should know first? (optional)',
  '例如：住喺深水埗，鍾意飲茶': 'e.g. lived in Sham Shui Po, loved dim sum',
  '其他模式': 'Other modes',
  '模式': 'Mode',
  '回憶整理（AI 同你一齊講佢）': 'Memory keeper (the AI talks about them with you)',
  '回憶整理': 'Memory keeper',
  '回憶連結': 'Memorial companion',
  '幻想伙伴': 'Fictional companion',
  '容許雙方自願嘅成人戀愛與親密內容': 'Allow consensual adult romance and intimate content',
  '我確認自己已年滿 18 歲': 'I confirm I am 18 or older',
  '取消': 'Cancel',
  '建立相簿，揀相': 'Create album and add photos',
  '未能建立相簿': 'Could not create the album',

  // Album
  '回憶相簿': 'Memory album',
  '轉換相簿': 'Switch album',
  '設定': 'Settings',
  '搵相': 'Search photos',
  '搵相：人物、地點、年份或者故事': 'Search: people, places, years or stories',
  '搵': 'Search',
  '搵緊…': 'Searching…',
  '清除': 'Clear',
  '搵到 {0} 張「{1}」': '{0} photos for "{1}"',
  '搵唔到「{0}」': 'Nothing found for "{0}"',
  '按相關程度排列': 'Most relevant first',
  '試下用人名、地點或者年份，例如「長洲」、「2019」。': 'Try a name, a place or a year, such as "Cheung Chau" or "2019".',
  'AI 搜尋暫時用唔到，而家只係用文字搵。': 'AI search is unavailable right now, so this is a plain text search.',
  '而家冇網，只係喺手機入面用文字搵。': 'You are offline, so this searches the text saved on your phone.',
  '連唔到伺服器，只係喺手機入面用文字搵。': 'Could not reach the server, so this searches the text saved on your phone.',
  '今日講一張': 'One photo today',
  '呢張相仲未有故事，講兩句俾 AI 記低？': 'This photo has no story yet. Tell the AI a little about it?',
  '講故事': 'Tell the story',
  '全部相片': 'All photos',
  '{0} 張': '{0} photos',
  ' · {0} 張未有故事': ' · {0} without a story',
  '未命名回憶': 'Untitled memory',
  '未有日期': 'No date',
  '未有故事': 'No story yet',
  '索引中': 'Indexing',
  '未能搜尋': 'Not searchable',
  '正在整理相簿…': 'Loading the album…',
  '仲未有相片': 'No photos yet',
  '加入第一張相，AI 會幫你理解內容，之後你可以慢慢講故事。': 'Add your first photo. The AI will look at what is in it, and you can tell its story whenever you like.',
  '加入相片': 'Add photos',
  '未能載入相簿': 'Could not load the album',
  '載入中': 'Loading',

  // Photo detail and story interview
  '‹ 返回相簿': '‹ Back to album',
  '✦ 同 AI 講呢張相嘅故事': '✦ Tell the AI this photo\'s story',
  'AI 已經將你講嘅故事整理成描述。請檢查一下，撳「儲存修改」先會保存。': 'The AI has written up your story. Please check it; it is only saved when you tap "Save changes".',
  'AI 暫時整理唔到，已經將你講嘅原文加入描述。請檢查一下，撳「儲存修改」先會保存。': 'The AI could not write it up, so your own words were added to the description. Please check it; it is only saved when you tap "Save changes".',
  '回憶描述': 'Description',
  '人物、地點或標籤': 'People, places or tags',
  '拍攝日期': 'Date taken',
  '對話展示': 'Show in conversation',
  '只在我要求時': 'Only when I ask',
  '相關時可以顯示': 'When it is relevant',
  '不在對話顯示': 'Never in conversation',
  '敏感度': 'Sensitivity',
  '一般回憶': 'Ordinary memory',
  '成人內容': 'Adult content',
  'AI 圖片描述': 'What the AI sees',
  '正在分析圖片…': 'Looking at the photo…',
  '未能自動分析呢張相片': 'The AI could not analyse this photo',
  '已加入對話搜尋': 'Searchable in conversation',
  '正在建立搜尋索引…': 'Building the search index…',
  '未能建立搜尋索引，對話暫時搵唔到呢張相': 'Indexing failed, so conversation cannot find this photo yet',
  '重試': 'Retry',
  '刪除相片': 'Delete photo',
  '儲存修改': 'Save changes',
  '儲存中…': 'Saving…',
  '永久刪除呢張相？刪除後無法復原。': 'Delete this photo permanently? This cannot be undone.',
  '未能刪除相片': 'Could not delete the photo',
  '未能更新相片': 'Could not update the photo',
  '未能重新建立索引': 'Could not rebuild the index',
  '準備問題中…': 'Preparing questions…',
  'AI 正喺度整理你講嘅故事…': 'The AI is writing up your story…',
  '第 {0}／{1} 條 · 唔記得可以跳過': 'Question {0} of {1} · skip anything you can\'t remember',
  '講幾多都得': 'Say as much or as little as you like',
  '跳過': 'Skip',
  '跳過並整理': 'Skip and write up',
  '下一條': 'Next',
  '整理成描述': 'Write it up',
  '夠啦，整理成描述': 'That\'s enough, write it up',
  '未能開始': 'Could not start',
  '未能整理描述': 'Could not write up the description',

  // Adding photos
  '加入回憶相片': 'Add memory photos',
  '相片只會屬於你同 {0}。AI 會分析相片內容，方便之後搜尋；人物同故事可以之後再同 AI 慢慢講。': 'These photos belong to you and {0}\'s album only. The AI looks at what is in each photo so you can search later; people and stories can be added with the AI afterwards.',
  '相片（可以一次揀多張；JPEG、PNG、WebP、HEIC／HEIF，每張最多 50 MB）': 'Photos (choose several at once; JPEG, PNG, WebP, HEIC/HEIF, up to 50 MB each)',
  '揀多張時，下面嘅描述、標籤同日期會套用落每一張。之後可以逐張同 AI 講故事。': 'When you choose several, the description, tags and date below apply to every photo. You can tell each photo\'s story with the AI afterwards.',
  '呢段回憶係關於咩？（選填）': 'What is this memory about? (optional)',
  '模型睇唔到人物身份同相片背後故事，建議你補充。': 'The AI cannot tell who people are or the story behind a photo, so it helps to add that.',
  '例如：長洲、生日、2022': 'e.g. Cheung Chau, birthday, 2022',
  '展示方式': 'Show in conversation',
  '只在我要求相片時顯示': 'Only when I ask for a photo',
  '對話相關時可以顯示': 'When it is relevant to the conversation',
  '保存但不在對話顯示': 'Keep it, but never show it in conversation',
  '正在上載…': 'Uploading…',
  '正在上載第 {0}／{1} 張…': 'Uploading {0} of {1}…',
  '保存回憶': 'Save photos',
  '請揀最少一張相。': 'Please choose at least one photo.',
  '未能上載': 'upload failed',
  '未能上載回憶': 'Could not upload the photo',
  '{0} 張已經保存，以下 {1} 張未能上載，只需要重新揀呢幾張：{2}': '{0} saved. These {1} failed, so only choose them again: {2}',
  '已保存 {0} 張相。AI 正喺背景分析，完成後對話就搵得到。': '{0} photos saved. The AI is analysing them in the background; conversation can find them once that finishes.',

  // Reminiscing (chat)
  '相簿': 'Album',
  '加相': 'Add photos',
  '講回憶': 'Reminisce',
  '主要導覽': 'Main navigation',
  '返相簿': 'Back to album',
  '講返{0}嘅事': 'Talking about {0}',
  '回憶整理助手': 'Memory keeper',
  '· 說明': '· About',
  '今日想講{0}邊件事？': 'What would you like to remember about {0} today?',
  '你講過嘅嘢 AI 會記住，講到相關相片會拎出嚟。想搵相，可以用相簿頂部嘅搜尋。AI 唔會扮演{0}。': 'The AI remembers what you tell it and brings up related photos. To find a photo, use the search at the top of the album. The AI never pretends to be {0}.',
  '有啲說話，慢慢講。': 'Take your time.',
  '呢個空間只屬於你同 {0}。': 'This space belongs only to you and {0}.',
  '我想講下{0}以前嘅一件事': 'I\'d like to tell you something about {0}',
  '我好掛住{0}': 'I really miss {0}',
  '{0}以前最鍾意做咩？': 'What did {0} love doing most?',
  '今日突然想同你傾下偈': 'I just felt like a chat today',
  '正在整理說話': 'Thinking',
  '關閉': 'Close',
  '訊息': 'Message',
  '講關於{0}嘅事…': 'Say something about {0}…',
  '輸入訊息…': 'Type a message…',
  '發送': 'Send',
  '請先輸入訊息。': 'Please type a message first.',
  '上一段說話仲未回覆完。': 'The previous reply is still coming.',
  '對話仍在準備中。': 'The conversation is still getting ready.',
  '正在回覆…': 'Replying…',
  '暫時未能回答': 'Could not reply just now',
  '無法打開對話': 'Could not open the conversation',
  '無法載入': 'Could not load',
  '你保存嘅回憶': 'Your saved memory',
  '正在載入私人相片…': 'Loading your private photo…',
  '＋ 加入呢張相嘅故事': '＋ Add to this photo\'s story',
  '加入相片故事': 'Add to the photo\'s story',
  '而家嘅描述': 'Current description',
  '你想加入嘅內容': 'What you would like to add',
  '例如：嗰日婆婆請我食燒賣，因為我考完會考': 'e.g. Grandma treated me to siu mai that day because I had finished my exams',
  '只會加入你講嘅嘢，AI 嘅回覆唔會當成事實。': 'Only your own words are added; the AI\'s replies are never treated as fact.',
  'AI 整理緊…': 'The AI is writing…',
  'AI 已經將新內容同原有描述合併。請檢查一下，撳「保存」先會寫入。': 'The AI has merged this with the existing description. Please check it; it is only saved when you tap "Save".',
  'AI 暫時整理唔到，已經將你嘅原文加喺原有描述後面。請檢查一下，撳「保存」先會寫入。': 'The AI could not write it up, so your words were added after the existing description. Please check it; it is only saved when you tap "Save".',
  '新嘅描述': 'New description',
  '標籤': 'Tags',
  '返回修改': 'Back to edit',
  '保存': 'Save',
  '保存緊…': 'Saving…',
  '未能保存': 'Could not save',
  '搵唔到呢張相': 'Could not find this photo',
  '喺講回憶入面補充嘅故事': 'A story added while reminiscing',
  '已經加入相片故事。AI 正喺背景更新搜尋。': 'Added to the photo\'s story. The AI is updating search in the background.',

  // Settings and sheets
  '你嘅相簿': 'Your albums',
  '＋ 為另一個人整理回憶': '＋ Keep memories of someone else',
  '回答由 AI 生成。相片、故事同對話屬於你呢個帳戶。': 'Replies are generated by AI. Photos, stories and conversations belong to your account.',
  'AI 會用第三身同你一齊講{0}，唔會扮演佢；冇資料嘅細節會反問你，唔會亂作。': 'The AI talks about {0} with you in the third person and never pretends to be them. When it lacks a detail it asks you instead of making one up.',
  '永久刪除「{0}」嘅相簿': 'Delete {0}\'s album permanently',
  '永久刪除「{0}」嘅相簿？\n\n所有相片、故事同對話都會一併刪除，而且無法復原。': 'Delete {0}\'s album permanently?\n\nAll photos, stories and conversations will be deleted and cannot be recovered.',
  '未能刪除相簿': 'Could not delete the album',
  '登出': 'Sign out',
  '完成': 'Done',

  // Offline and network
  '而家冇網：可以睇相同故事，搜尋只用文字': 'Offline: you can view photos and stories; search is text only',
  '而家冇網：可以睇返對話，有網先講得': 'Offline: you can read the conversation; replies need a connection',
  '而家冇網絡連線，有網先再試。': 'You are offline. Try again when you have a connection.',
  '連唔到伺服器，請稍後再試。': 'Could not reach the server. Please try again shortly.',
  '暫時未能完成操作': 'That could not be completed just now',
  '伺服器暫時未能完成操作 ({0})': 'The server could not complete that ({0})',

  // Print quality
  '印刷清晰度': 'Print quality',
  '好（約 {0} dpi），印成 A5 全頁都清楚。': 'Good (about {0} dpi). Sharp even as a full A5 page.',
  '可以接受（約 {0} dpi），印成 A5 全頁會略為柔和；印細啲就清楚。': 'Acceptable (about {0} dpi). Slightly soft as a full A5 page; sharp when printed smaller.',
  '偏低（約 {0} dpi），印出嚟會矇。手上有原本嘅相或者實體相嘅話，用掃描版會清楚好多。': 'Low (about {0} dpi). It will look blurry in print. If you have the original file or the physical print, a scan will look much better.',

  // Language settings
  '介面語言': 'App language',
  '相簿語言': 'Album language',
  'AI 會用呢個語言問問題同描述相片。你用咩語言答，佢就用咩語言整理。': 'The AI asks questions and describes photos in this language. Whatever language you answer in is the language it writes in.',
};
