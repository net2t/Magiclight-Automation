// ============================================================
// BLS YouTube Uploader — Apps Script Backend
// Version 2.0 — NeoBrutalism Dashboard Compatible
// ============================================================

const SHEET_URL = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vQrwn7Tei_9QBxtJ-Ka_wGtKNISq4TfafHKu2ANAiACNOZagNrl6uG2WghkPogOQNUXsDb618bFMqbB/pub?gid=2087344095&single=true&output=csv';

// Column indices (0-based) — adjust if sheet changes
const COL = {
  STATUS: 0,      // A - Status
  THEME: 1,       // B - Theme
  TITLE: 2,       // C - Title
  STORY: 3,       // D - Story
  MORAL: 4,       // E - Moral
  GEN_TITLE: 5,   // F - Gen_Title
  GEN_SUMMARY: 6, // G - Gen_Summary
  GEN_TAGS: 7,    // H - Gen_Tags
  PROJECT_URL: 8, // I - Project_URL
  CREATED: 9,     // J - Created_Time
  COMPLETED: 10,  // K - Completed_Time
  NOTES: 11,      // L - Notes
  DRIVE_LINK: 12, // M - Drive_Link (VIDEO)
  DRIVEIMG_LINK: 13, // N - DriveImg_Link (THUMBNAIL)
  CREDIT_BEFORE: 14, // O
  CREDIT_AFTER: 15,  // P
  EMAIL_USED: 16,    // Q - Email_Used
};

// ─── THEME → CHANNEL MAPPING ─────────────────────────────────
// Store in Script Properties for security
// Key format: CHANNEL_ID_Teamwork, OAUTH_TOKEN_Teamwork, etc.
function getThemeConfig(theme) {
  const props = PropertiesService.getScriptProperties();
  return {
    channelId: props.getProperty('CHANNEL_ID_' + theme) || '',
    oauthToken: props.getProperty('OAUTH_TOKEN_' + theme) || '',
    category: props.getProperty('CATEGORY_' + theme) || '27',
    privacy: props.getProperty('PRIVACY_' + theme) || 'public',
    email: props.getProperty('EMAIL_' + theme) || '',
    playlistId: props.getProperty('PLAYLIST_ID_' + theme) || '',
  };
}

function setThemeConfig(theme, channelId, email, category, privacy) {
  const props = PropertiesService.getScriptProperties();
  props.setProperty('CHANNEL_ID_' + theme, channelId);
  props.setProperty('EMAIL_' + theme, email);
  props.setProperty('CATEGORY_' + theme, category);
  props.setProperty('PRIVACY_' + theme, privacy);
  Logger.log('Config saved for theme: ' + theme);
}

// ─── SETUP: Run once per theme to authorize ──────────────────
function setupThemes() {
  // Edit these to match your channels
  setThemeConfig('Teamwork', 'UCxxxxxxxxTEAMWORK', 'kakife5916@nyspring.com', '27', 'public');
  setThemeConfig('Adventure', 'UCxxxxxxxxADVENTURE', 'noyisad279@parsitv.com', '27', 'public');
  setThemeConfig('Animals', 'UCxxxxxxxxANIMALS', 'rokak74566@parsitv.com', '27', 'public');
  setThemeConfig('Kindness', 'UCxxxxxxxxKINDNESS', 'kindness@gmail.com', '27', 'public');
  setThemeConfig('Humor', 'UCxxxxxxxxHUMOR', 'humor@gmail.com', '23', 'public');
  Logger.log('All theme configs saved!');
}

// ─── GOOGLE SHEET DATA ───────────────────────────────────────
function getSheetData() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheets()[0];
  const data = sheet.getDataRange().getValues();
  const headers = data[0];
  return data.slice(1).map((row, i) => ({
    rowIndex: i + 2, // 1-indexed, skip header
    status: row[COL.STATUS],
    theme: row[COL.THEME],
    title: row[COL.TITLE],
    story: row[COL.STORY],
    moral: row[COL.MORAL],
    genTitle: row[COL.GEN_TITLE],
    genSummary: row[COL.GEN_SUMMARY],
    genTags: row[COL.GEN_TAGS],
    projectUrl: row[COL.PROJECT_URL],
    createdTime: row[COL.CREATED],
    completedTime: row[COL.COMPLETED],
    driveLink: row[COL.DRIVE_LINK],
    driveImgLink: row[COL.DRIVEIMG_LINK],
    emailUsed: row[COL.EMAIL_USED],
    notes: row[COL.NOTES],
  }));
}

function isRowDone(row) {
  const v = (row && row.status != null) ? String(row.status).trim().toLowerCase() : '';
  return v === 'done' || v === 'completed' || v === 'uploaded';
}

// ─── EXTRACT DRIVE FILE ID ───────────────────────────────────
function extractDriveId(url) {
  if (!url) return null;
  const match = url.match(/\/d\/([a-zA-Z0-9_-]{10,})/);
  return match ? match[1] : null;
}

// ─── CONVERT DRIVE LINK TO DOWNLOADABLE ──────────────────────
function getDriveBlob(driveUrl) {
  const fileId = extractDriveId(driveUrl);
  if (!fileId) throw new Error('Invalid Drive URL: ' + driveUrl);
  const file = DriveApp.getFileById(fileId);
  return { blob: file.getBlob(), name: file.getName(), mimeType: file.getMimeType() };
}

// ─── MAIN UPLOAD FUNCTION ────────────────────────────────────
function uploadVideoToYouTube(options) {
  /*
    options = {
      theme, title, description, tags (array), categoryId,
      privacy, driveVideoUrl, driveThumbnailUrl,
      language, madeForKids, embeddable, notifySubscribers,
      publishAt (ISO string for scheduled, null for immediate),
      license, playlistId
    }
  */
  const config = getThemeConfig(options.theme);
  if (!config.channelId) throw new Error('No channel configured for theme: ' + options.theme);

  // Get video blob from Drive
  const videoData = getDriveBlob(options.driveVideoUrl);

  // Build resource metadata
  const resource = {
    snippet: {
      title: options.title,
      description: options.description || '',
      tags: Array.isArray(options.tags) ? options.tags : (options.tags || '').split(',').map(t => t.trim()),
      categoryId: options.categoryId || config.category || '27',
      defaultLanguage: options.language || 'en',
      defaultAudioLanguage: options.language || 'en',
    },
    status: {
      privacyStatus: options.privacy || config.privacy || 'public',
      selfDeclaredMadeForKids: options.madeForKids || false,
      embeddable: options.embeddable !== false,
      license: options.license || 'youtube',
      publishAt: options.publishAt || null,
      notifySubscribers: options.notifySubscribers !== false,
    },
  };

  // If scheduled, must be private first
  if (options.publishAt) {
    resource.status.privacyStatus = 'private';
  }

  Logger.log('Uploading: ' + options.title);
  Logger.log('Theme: ' + options.theme + ' → Channel: ' + config.channelId);

  const videoInsert = YouTube.Videos.insert(
    resource,
    'snippet,status',
    videoData.blob
  );

  const videoId = videoInsert.id;
  Logger.log('Upload SUCCESS — Video ID: ' + videoId);

  // Upload thumbnail if provided
  if (options.driveThumbnailUrl && videoId) {
    try {
      const thumbData = getDriveBlob(options.driveThumbnailUrl);
      YouTube.Thumbnails.set(videoId, thumbData.blob);
      Logger.log('Thumbnail set successfully');
    } catch (e) {
      Logger.log('Thumbnail upload failed (non-fatal): ' + e.message);
    }
  }

  // Add to playlist if provided
  if (options.playlistId && videoId) {
    try {
      YouTube.PlaylistItems.insert({
        snippet: {
          playlistId: options.playlistId,
          resourceId: { kind: 'youtube#video', videoId }
        }
      }, 'snippet');
      Logger.log('Added to playlist: ' + options.playlistId);
    } catch (e) {
      Logger.log('Playlist insert failed (non-fatal): ' + e.message);
    }
  }

  return { success: true, videoId, url: 'https://youtube.com/watch?v=' + videoId };
}

// ─── LOG TO SHEET ────────────────────────────────────────────
function logUpload(rowIndex, videoId, status, notes) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheets()[0];

  const rowVals = sheet.getRange(rowIndex, 1, 1, COL.EMAIL_USED + 1).getValues()[0];
  const title = rowVals[COL.GEN_TITLE] || rowVals[COL.TITLE] || '';
  const theme = rowVals[COL.THEME] || '';

  // Mark as Done
  if (status === 'success') {
    sheet.getRange(rowIndex, COL.STATUS + 1).setValue('Done');
    sheet.getRange(rowIndex, COL.COMPLETED + 1).setValue(new Date().toISOString());
    sheet.getRange(rowIndex, COL.PROJECT_URL + 1).setValue('https://youtube.com/watch?v=' + videoId);
  } else if (status === 'failed') {
    sheet.getRange(rowIndex, COL.STATUS + 1).setValue('Error');
  }
  sheet.getRange(rowIndex, COL.NOTES + 1).setValue(notes || '');

  // Write to Log sheet
  let logSheet = ss.getSheetByName('Upload_Log');
  if (!logSheet) {
    logSheet = ss.insertSheet('Upload_Log');
    logSheet.appendRow(['Timestamp', 'Row', 'Title', 'Theme', 'Status', 'Video ID', 'YouTube URL', 'Notes']);
    logSheet.getRange(1, 1, 1, 8).setFontWeight('bold').setBackground('#0a0a0a').setFontColor('#FFE500');
  }
  logSheet.appendRow([
    new Date(), rowIndex, title, theme, status,
    videoId || '', videoId ? 'https://youtube.com/watch?v=' + videoId : '', notes || ''
  ]);
}

// ─── SINGLE MANUAL UPLOAD (call from dashboard) ──────────────
function uploadSingleRow(rowIndex) {
  const data = getSheetData();
  const row = data.find(r => r.rowIndex === rowIndex);
  if (!row) { Logger.log('Row not found: ' + rowIndex); return; }
  if (isRowDone(row)) { Logger.log('Already uploaded, skipping row ' + rowIndex); return; }

  try {
    const result = uploadVideoToYouTube({
      theme: row.theme,
      title: row.genTitle || row.title,
      description: buildDescription(row),
      tags: (row.genTags || row.theme).split(',').map(t => t.trim()),
      driveVideoUrl: row.driveLink,
      driveThumbnailUrl: row.driveImgLink,
      privacy: 'public',
      madeForKids: true,
      language: 'en',
    });
    logUpload(row.rowIndex, result.videoId, 'success', 'Uploaded: ' + new Date().toLocaleString());
    Logger.log('Done: ' + result.url);
  } catch (e) {
    logUpload(row.rowIndex, null, 'failed', 'Error: ' + e.message);
    Logger.log('FAILED: ' + e.message);
  }
}

// ─── AUTO-UPLOAD TRIGGER FUNCTION ────────────────────────────
function autoUpload() {
  const data = getSheetData();
  const pending = data.filter(r => !isRowDone(r) && r.driveLink);
  const maxPerRun = 2; // Upload max 2 per trigger run
  let count = 0;

  for (const row of pending) {
    if (count >= maxPerRun) break;
    try {
      Logger.log('Auto-uploading row ' + row.rowIndex + ': ' + (row.genTitle || row.title));
      const result = uploadVideoToYouTube({
        theme: row.theme,
        title: row.genTitle || row.title,
        description: buildDescription(row),
        tags: (row.genTags || row.theme).split(',').map(t => t.trim()),
        driveVideoUrl: row.driveLink,
        driveThumbnailUrl: row.driveImgLink,
        privacy: 'public',
        madeForKids: true,
        language: 'en',
      });
      logUpload(row.rowIndex, result.videoId, 'success', 'Auto-uploaded');
      count++;
      Utilities.sleep(3000); // 3 second delay between uploads
    } catch (e) {
      logUpload(row.rowIndex, null, 'failed', 'Auto error: ' + e.message);
      Logger.log('Auto-upload failed row ' + row.rowIndex + ': ' + e.message);
    }
  }
  Logger.log('Auto-upload complete. Uploaded: ' + count);
}

// ─── DESCRIPTION BUILDER ─────────────────────────────────────
function buildDescription(row) {
  return `${row.genSummary || row.story || ''}

Moral of the story: ${row.moral || ''}

#${(row.theme || 'story').replace(/\s+/g, '')} #KidsStory #AnimatedStory #MoralStory #BLStories

📺 Watch more stories on our channel!
👍 Like, Subscribe & Share with friends.`;
}

// ─── TRIGGER MANAGEMENT ──────────────────────────────────────
function setDailyTrigger(hourPKT) {
  // Delete existing triggers first
  deleteTrigger();

  // PKT = UTC+5, so subtract 5 for UTC hour
  const hourUTC = (parseInt(hourPKT) - 5 + 24) % 24;

  ScriptApp.newTrigger('autoUpload')
    .timeBased()
    .everyDays(1)
    .atHour(hourUTC)
    .create();

  Logger.log('Daily trigger set for ' + hourPKT + ':00 PKT (' + hourUTC + ':00 UTC)');
}

function deleteTrigger() {
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(t => {
    if (t.getHandlerFunction() === 'autoUpload') {
      ScriptApp.deleteTrigger(t);
      Logger.log('Deleted trigger: ' + t.getUniqueId());
    }
  });
}

function listTriggers() {
  ScriptApp.getProjectTriggers().forEach(t => {
    Logger.log(t.getHandlerFunction() + ' — ' + t.getEventType());
  });
}

// ─── SETUP CONFIG SHEET ──────────────────────────────────────
function setupConfigSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let config = ss.getSheetByName('YT_Config');
  if (!config) config = ss.insertSheet('YT_Config');
  config.clearContents();

  const headers = ['Theme', 'Channel Name', 'Channel ID', 'Email', 'Default Category', 'Default Privacy', 'Playlist ID', 'Status'];
  config.appendRow(headers);
  config.getRange(1, 1, 1, headers.length).setFontWeight('bold').setBackground('#0a0a0a').setFontColor('#FFE500');

  // Default rows
  const defaults = [
    ['Teamwork', 'Magic Stories HQ', 'UCxxxxxxxxTEAMWORK', 'kakife5916@nyspring.com', '27', 'public', '', 'Active'],
    ['Adventure', 'Adventure Tales', 'UCxxxxxxxxADVENTURE', 'noyisad279@parsitv.com', '27', 'public', '', 'Active'],
    ['Animals', 'Animal Friends', 'UCxxxxxxxxANIMALS', 'rokak74566@parsitv.com', '27', 'public', '', 'Active'],
    ['Kindness', 'Kindness Corner', 'UCxxxxxxxxKINDNESS', '', '27', 'public', '', 'Pending'],
    ['Humor', 'Funny Pals', 'UCxxxxxxxxHUMOR', '', '23', 'public', '', 'Pending'],
  ];
  defaults.forEach(row => config.appendRow(row));
  config.autoResizeColumns(1, headers.length);
  Logger.log('Config sheet created! Fill in Channel IDs and Emails.');
}

// ─── READ CONFIG FROM SHEET ──────────────────────────────────
function syncConfigFromSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const config = ss.getSheetByName('YT_Config');
  if (!config) { Logger.log('No YT_Config sheet found. Run setupConfigSheet() first.'); return; }
  const data = config.getDataRange().getValues().slice(1);
  data.forEach(row => {
    const [theme, , channelId, email, category, privacy, playlistId, status] = row;
    if (!theme) return;
    if (status && String(status).trim().toLowerCase() !== 'active') return;
    setThemeConfig(theme, channelId, email, category, privacy);
    if (playlistId) {
      PropertiesService.getScriptProperties().setProperty('PLAYLIST_ID_' + theme, playlistId);
    }
  });
  Logger.log('Config synced from sheet!');
}

// ─── CHECK QUOTA ─────────────────────────────────────────────
function checkQuota() {
  try {
    const result = YouTube.Channels.list('id', { mine: true });
    Logger.log('API connection OK. Channel count: ' + (result.items || []).length);
  } catch (e) {
    Logger.log('Quota/Auth error: ' + e.message);
  }
}

// ─── WEB APP ENTRY POINT ─────────────────────────────────────
function doGet(e) {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('BLS YouTube Uploader')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

// Called from web app via google.script.run
function getStoriesFromSheet() {
  return getSheetData();
}

function uploadFromWebApp(rowIndex, overrides) {
  const data = getSheetData();
  const row = data.find(r => r.rowIndex === rowIndex);
  if (!row) return { error: 'Row not found' };
  try {
    const cfg = getThemeConfig(row.theme);
    const result = uploadVideoToYouTube({
      theme: row.theme,
      title: overrides.title || row.genTitle || row.title,
      description: overrides.description || buildDescription(row),
      tags: (overrides.tags || row.genTags || '').split(',').map(t => t.trim()),
      categoryId: overrides.categoryId || '27',
      privacy: overrides.privacy || 'public',
      language: overrides.language || 'en',
      madeForKids: overrides.madeForKids || false,
      embeddable: overrides.embeddable !== false,
      notifySubscribers: overrides.notifySubscribers !== false,
      publishAt: overrides.publishAt || null,
      license: overrides.license || 'youtube',
      playlistId: overrides.playlistId || cfg.playlistId || null,
      driveVideoUrl: row.driveLink,
      driveThumbnailUrl: row.driveImgLink,
    });
    logUpload(row.rowIndex, result.videoId, 'success', 'Web app upload');
    return result;
  } catch (e) {
    logUpload(row.rowIndex, null, 'failed', e.message);
    return { error: e.message };
  }
}
