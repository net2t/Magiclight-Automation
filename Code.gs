/**
 * MagicLight Pro — Google Apps Script Backend v3.0
 * ==================================================
 * Multi-account OAuth 2.0 YouTube uploader with:
 *   - Multi-account management (add / remove / de-auth)
 *   - Sheet row view / edit / delete
 *   - Scheduled uploads (time-based triggers)
 *   - YouTube Analytics (views, likes, comments)
 *   - Upload activity log
 *
 * FIRST-TIME SETUP (run once in order):
 *   1. Apps Script → Services → Add "YouTube Data API v3"
 *   2. Apps Script → Services → Add "YouTube Analytics API"
 *   3. Deploy → New Deployment → Web App
 *        Execute as : Me
 *        Who access : Anyone
 *   4. Copy the Web App URL → paste into index.html CFG.APPS_SCRIPT_URL
 *   5. Open Web App URL in browser → it will trigger OAuth for Account 1
 *   6. To add more accounts: use "Add Account" in Config tab of dashboard
 */


// ─────────────────────────────────────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────────────────────────────────────

// Google Sheet ID — change this to your actual sheet ID
// Found in sheet URL: docs.google.com/spreadsheets/d/SHEET_ID/edit
var SHEET_ID   = '1p5sg2j-6IZhbj-7s2giJM_9e9rWnK-ixgcrt3jgR7Gc'; // ← paste your Sheet ID here

// Sheet tab name that holds story data
var SHEET_NAME = 'Database';

// Log sheet tab name (auto-created if missing)
var LOG_SHEET  = 'UploadLog';

// Script Properties keys used for storing OAuth tokens per account
// Format: TOKEN_account1@gmail.com → JSON token string
var TOKEN_PREFIX = 'TOKEN_';

// Column mapping — matches your sheet layout exactly
// Col A=1, B=2 ... U=21
var COL = {
  Status:          1,   // A
  Theme:           2,   // B
  Title:           3,   // C
  Story:           4,   // D
  Moral:           5,   // E
  Gen_Title:       6,   // F
  Gen_Summary:     7,   // G
  Gen_Tags:        8,   // H
  Project_URL:     9,   // I
  Created_Time:   10,   // J
  Completed_Time: 11,   // K
  Notes:          12,   // L
  Drive_Link:     13,   // M
  DriveImg_Link:  14,   // N
  Credit_Before:  15,   // O
  Credit_After:   16,   // P
  Email_Used:     17,   // Q
  YouTube_ID:     18,   // R  ← stores uploaded video ID
  YouTube_URL:    19,   // S  ← full YouTube link
  Schedule_Time:  20,   // T  ← ISO datetime string for scheduled upload
  Done:           21    // U  ← TRUE/FALSE upload done flag
};


// ─────────────────────────────────────────────────────────────────────────────
// HTTP ENTRY POINTS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * doPost — handles all dashboard API calls
 * Every request sends JSON: { action: 'actionName', ...params }
 */
function doPost(e) {
  try {
    var data   = JSON.parse(e.postData.contents);
    var action = data.action || '';
    var result;

    // Route to correct handler based on action name
    switch (action) {

      // ── Sheet operations ──────────────────────────────
      case 'getRows':         result = getRows(data);         break;
      case 'updateRow':       result = updateRow(data);       break;
      case 'deleteRow':       result = deleteRow(data);       break;
      case 'getStats':        result = getStats();            break;

      // ── YouTube upload ────────────────────────────────
      case 'uploadToYouTube': result = uploadToYouTube(data); break;

      // ── Schedule ──────────────────────────────────────
      case 'scheduleUpload':  result = scheduleUpload(data);  break;
      case 'getScheduled':    result = getScheduled();        break;
      case 'cancelSchedule':  result = cancelSchedule(data);  break;

      // ── Accounts ──────────────────────────────────────
      case 'getAccounts':     result = getAccounts();         break;
      case 'addAccount':      result = addAccount(data);      break;
      case 'removeAccount':   result = removeAccount(data);   break;
      case 'deauthAccount':   result = deauthAccount(data);   break;

      // ── Analytics ─────────────────────────────────────
      case 'getAnalytics':    result = getAnalytics(data);    break;
      case 'getAllAnalytics':  result = getAllAnalytics();     break;

      // ── Log ───────────────────────────────────────────
      case 'getLogs':         result = getLogs(data);         break;
      case 'clearLogs':       result = clearLogs();           break;

      // ── Config ────────────────────────────────────────
      case 'getConfig':       result = getConfig();           break;
      case 'saveConfig':      result = saveConfig(data);      break;

      default:
        result = { success: false, error: 'Unknown action: ' + action };
    }

    return _json(result);

  } catch (err) {
    _writeLog('ERROR', 'doPost', err.toString());
    return _json({ success: false, error: err.toString() });
  }
}

/**
 * doGet — health check + OAuth callback entry point
 * When user opens Web App URL in browser, OAuth flow starts here
 */
function doGet(e) {
  // OAuth callback: ?code=xxx&state=email@gmail.com
  if (e && e.parameter && e.parameter.code) {
    return _handleOAuthCallback(e);
  }
  return _json({ status: 'MagicLight Pro v3.0 online', time: new Date().toISOString() });
}


// ─────────────────────────────────────────────────────────────────────────────
// SHEET OPERATIONS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * getRows — returns all rows from sheet
 * Params: { page, pageSize, filter, search }
 * Returns: { rows[], total, page, pages }
 */
function getRows(params) {
  var ws      = _getSheet();
  var all     = ws.getDataRange().getValues();
  var headers = all[0]; // row 1 = headers

  // Build array of row objects (skip header row)
  var rows = [];
  for (var i = 1; i < all.length; i++) {
    var r   = all[i];
    var obj = {
      rowNum:        i + 1,           // actual sheet row number (1-indexed, header=1)
      status:        r[COL.Status - 1]        || '',
      theme:         r[COL.Theme - 1]         || '',
      title:         r[COL.Title - 1]         || '',
      story:         r[COL.Story - 1]         || '',
      moral:         r[COL.Moral - 1]         || '',
      gen_title:     r[COL.Gen_Title - 1]     || '',
      gen_summary:   r[COL.Gen_Summary - 1]   || '',
      gen_tags:      r[COL.Gen_Tags - 1]      || '',
      project_url:   r[COL.Project_URL - 1]   || '',
      created_time:  r[COL.Created_Time - 1]  || '',
      completed_time:r[COL.Completed_Time - 1]|| '',
      notes:         r[COL.Notes - 1]         || '',
      drive_link:    r[COL.Drive_Link - 1]    || '',
      driveimg_link: r[COL.DriveImg_Link - 1] || '',
      credit_before: r[COL.Credit_Before - 1] || '',
      credit_after:  r[COL.Credit_After - 1]  || '',
      email_used:    r[COL.Email_Used - 1]    || '',
      youtube_id:    r[COL.YouTube_ID - 1]    || '',
      youtube_url:   r[COL.YouTube_URL - 1]   || '',
      schedule_time: r[COL.Schedule_Time - 1] || '',
      done:          r[COL.Done - 1]          || ''
    };
    rows.push(obj);
  }

  // ── Filter by status ──────────────────────────────────────────────────────
  var filterVal = (params && params.filter) ? params.filter.toLowerCase() : 'all';
  if (filterVal !== 'all') {
    rows = rows.filter(function(r) {
      return r.status.toLowerCase() === filterVal;
    });
  }

  // ── Search ────────────────────────────────────────────────────────────────
  var q = (params && params.search) ? params.search.toLowerCase() : '';
  if (q) {
    rows = rows.filter(function(r) {
      return (r.title + r.gen_title + r.theme + r.notes + r.moral).toLowerCase().indexOf(q) >= 0;
    });
  }

  var total = rows.length;

  // ── Pagination ────────────────────────────────────────────────────────────
  var pageSize = (params && params.pageSize) ? parseInt(params.pageSize) : 50;
  var page     = (params && params.page)     ? parseInt(params.page)     : 1;
  var start    = (page - 1) * pageSize;
  rows         = rows.slice(start, start + pageSize);

  return {
    success:  true,
    rows:     rows,
    total:    total,
    page:     page,
    pages:    Math.ceil(total / pageSize),
    pageSize: pageSize
  };
}

/**
 * updateRow — edit one or more cells in a sheet row
 * Params: { rowNum, fields: { fieldName: value, ... } }
 */
function updateRow(params) {
  if (!params.rowNum) return { success: false, error: 'rowNum required' };

  var ws     = _getSheet();
  var rowNum = parseInt(params.rowNum);
  var fields = params.fields || {};

  // Map field names to column indices and write each cell
  var colMap = {
    status:         COL.Status,
    theme:          COL.Theme,
    title:          COL.Title,
    story:          COL.Story,
    moral:          COL.Moral,
    gen_title:      COL.Gen_Title,
    gen_summary:    COL.Gen_Summary,
    gen_tags:       COL.Gen_Tags,
    project_url:    COL.Project_URL,
    created_time:   COL.Created_Time,
    completed_time: COL.Completed_Time,
    notes:          COL.Notes,
    drive_link:     COL.Drive_Link,
    driveimg_link:  COL.DriveImg_Link,
    credit_before:  COL.Credit_Before,
    credit_after:   COL.Credit_After,
    email_used:     COL.Email_Used,
    youtube_id:     COL.YouTube_ID,
    youtube_url:    COL.YouTube_URL,
    schedule_time:  COL.Schedule_Time,
    done:           COL.Done
  };

  var updated = [];
  for (var key in fields) {
    var colIdx = colMap[key.toLowerCase()];
    if (colIdx) {
      ws.getRange(rowNum, colIdx).setValue(fields[key]);
      updated.push(key);
    }
  }

  _writeLog('UPDATE', 'Row ' + rowNum, 'Fields: ' + updated.join(', '));
  return { success: true, rowNum: rowNum, updated: updated };
}

/**
 * deleteRow — permanently deletes a sheet row
 * Params: { rowNum }
 * WARNING: This is irreversible — row numbers of all rows below shift up
 */
function deleteRow(params) {
  if (!params.rowNum) return { success: false, error: 'rowNum required' };

  var ws     = _getSheet();
  var rowNum = parseInt(params.rowNum);

  // Safety: do not allow deleting header row (row 1)
  if (rowNum <= 1) return { success: false, error: 'Cannot delete header row' };

  // Read title for log before deleting
  var titleCell = ws.getRange(rowNum, COL.Title).getValue();
  ws.deleteRow(rowNum);

  _writeLog('DELETE', 'Row ' + rowNum, 'Title: ' + titleCell);
  return { success: true, rowNum: rowNum, title: titleCell };
}

/**
 * getStats — returns counts for dashboard stat cards
 */
function getStats() {
  var ws   = _getSheet();
  var data = ws.getDataRange().getValues();

  var total = data.length - 1; // subtract header
  var counts = { total: total, done: 0, pending: 0, generated: 0, error: 0, scheduled: 0 };

  for (var i = 1; i < data.length; i++) {
    var st = (data[i][COL.Status - 1] || '').toString().toLowerCase();
    if (st === 'done')                    counts.done++;
    else if (st === 'pending')            counts.pending++;
    else if (st === 'generated')          counts.generated++;
    else if (st === 'error' || st === 'no_video') counts.error++;
    // Count rows that have a scheduled time but not yet uploaded
    if (data[i][COL.Schedule_Time - 1] && !data[i][COL.Done - 1]) counts.scheduled++;
  }

  return { success: true, stats: counts };
}


// ─────────────────────────────────────────────────────────────────────────────
// YOUTUBE UPLOAD
// ─────────────────────────────────────────────────────────────────────────────

/**
 * uploadToYouTube — uploads a Drive video to YouTube for a specific account
 * Params: { rowNum, driveUrl, title, description, privacy, tags, accountEmail, thumbnailUrl }
 */
function uploadToYouTube(params) {
  var rowNum       = params.rowNum       || null;
  var driveUrl     = params.driveUrl     || '';
  var title        = params.title        || 'Story Video';
  var description  = params.description  || '';
  var privacy      = params.privacy      || 'public';
  var tags         = params.tags         || '';
  var accountEmail = params.accountEmail || '';
  var thumbnailUrl = params.thumbnailUrl || '';

  if (!driveUrl)     return { success: false, error: 'driveUrl required' };
  if (!accountEmail) return { success: false, error: 'accountEmail required' };

  // Extract Drive file ID from URL
  var fileId = _extractDriveId(driveUrl);
  if (!fileId) return { success: false, error: 'Could not extract Drive ID from: ' + driveUrl };

  try {
    // Get video blob from Drive
    var file = DriveApp.getFileById(fileId);
    var blob = file.getBlob();

    // Build video metadata
    var resource = {
      snippet: {
        title:       title.substring(0, 100),
        description: description,
        tags:        tags ? tags.split(',').map(function(t){ return t.trim(); }).filter(Boolean) : [],
        categoryId:  '27'   // Education
      },
      status: {
        privacyStatus:           privacy || 'public',
        selfDeclaredMadeForKids: true,
        embeddable:              true,
        publicStatsViewable:     true
      }
    };

    // Upload video using YouTube Data API
    var video = YouTube.Videos.insert(resource, 'snippet,status', blob);
    var videoId  = video.id;
    var videoUrl = 'https://youtu.be/' + videoId;

    // Upload custom thumbnail if provided
    if (thumbnailUrl) {
      _uploadThumbnail(videoId, thumbnailUrl);
    }

    // Write YouTube ID + URL back to sheet row
    if (rowNum) {
      var ws = _getSheet();
      ws.getRange(rowNum, COL.YouTube_ID).setValue(videoId);
      ws.getRange(rowNum, COL.YouTube_URL).setValue(videoUrl);
      ws.getRange(rowNum, COL.Done).setValue('TRUE');
      ws.getRange(rowNum, COL.Status).setValue('Done');
      ws.getRange(rowNum, COL.Email_Used).setValue(accountEmail);
      ws.getRange(rowNum, COL.Completed_Time).setValue(
        Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss')
      );
    }

    _writeLog('UPLOAD', accountEmail, 'Row:' + rowNum + ' → ' + videoUrl);
    return { success: true, videoId: videoId, url: videoUrl };

  } catch (err) {
    _writeLog('ERROR', 'uploadToYouTube', err.toString());
    return { success: false, error: err.toString() };
  }
}

/**
 * _uploadThumbnail — sets custom thumbnail on a YouTube video
 * Requires channel with 1000+ subscribers
 */
function _uploadThumbnail(videoId, thumbDriveUrl) {
  try {
    var thumbId   = _extractDriveId(thumbDriveUrl);
    if (!thumbId) return;
    var thumbFile = DriveApp.getFileById(thumbId);
    var thumbBlob = thumbFile.getBlob();
    YouTube.Thumbnails.set(videoId, thumbBlob);
  } catch (e) {
    Logger.log('[thumbnail] Failed: ' + e.toString());
    // Non-fatal — continue without thumbnail
  }
}


// ─────────────────────────────────────────────────────────────────────────────
// SCHEDULER
// ─────────────────────────────────────────────────────────────────────────────

/**
 * scheduleUpload — saves a scheduled time for a row's upload
 * Params: { rowNum, scheduleTime (ISO string), accountEmail }
 * The actual upload happens via autoUploadTrigger() time-based trigger
 */
function scheduleUpload(params) {
  if (!params.rowNum)       return { success: false, error: 'rowNum required' };
  if (!params.scheduleTime) return { success: false, error: 'scheduleTime required' };

  var ws = _getSheet();
  ws.getRange(params.rowNum, COL.Schedule_Time).setValue(params.scheduleTime);
  ws.getRange(params.rowNum, COL.Email_Used).setValue(params.accountEmail || '');

  _writeLog('SCHEDULE', params.accountEmail, 'Row:' + params.rowNum + ' at ' + params.scheduleTime);
  return { success: true, rowNum: params.rowNum, scheduleTime: params.scheduleTime };
}

/**
 * getScheduled — returns all rows that have a scheduled time but not yet uploaded
 */
function getScheduled() {
  var ws   = _getSheet();
  var data = ws.getDataRange().getValues();
  var rows = [];

  for (var i = 1; i < data.length; i++) {
    var schedTime = data[i][COL.Schedule_Time - 1];
    var isDone    = data[i][COL.Done - 1];
    if (schedTime && !isDone) {
      rows.push({
        rowNum:       i + 1,
        title:        data[i][COL.Gen_Title - 1] || data[i][COL.Title - 1] || '',
        scheduleTime: schedTime,
        accountEmail: data[i][COL.Email_Used - 1] || '',
        status:       data[i][COL.Status - 1] || ''
      });
    }
  }
  return { success: true, scheduled: rows };
}

/**
 * cancelSchedule — removes scheduled time from a row
 * Params: { rowNum }
 */
function cancelSchedule(params) {
  if (!params.rowNum) return { success: false, error: 'rowNum required' };
  var ws = _getSheet();
  ws.getRange(params.rowNum, COL.Schedule_Time).setValue('');
  _writeLog('CANCEL_SCHEDULE', 'Row ' + params.rowNum, '');
  return { success: true };
}

/**
 * autoUploadTrigger — called by Apps Script time-based trigger (every hour)
 * Checks for rows whose scheduleTime has passed and uploads them
 *
 * TO SET UP THE TRIGGER:
 *   Apps Script → Triggers (alarm icon) → Add Trigger
 *   Function: autoUploadTrigger
 *   Event: Time-driven → Hour timer → Every 1 hour
 */
function autoUploadTrigger() {
  var ws   = _getSheet();
  var data = ws.getDataRange().getValues();
  var now  = new Date();

  for (var i = 1; i < data.length; i++) {
    var schedTimeStr = data[i][COL.Schedule_Time - 1];
    var isDone       = data[i][COL.Done - 1];
    var driveLink    = data[i][COL.Drive_Link - 1];
    var accountEmail = data[i][COL.Email_Used - 1];

    if (!schedTimeStr || isDone || !driveLink) continue;

    var schedTime = new Date(schedTimeStr);

    // Upload if scheduled time has passed (within 2-hour window)
    if (schedTime <= now && (now - schedTime) < 2 * 60 * 60 * 1000) {
      var rowNum    = i + 1;
      var genTitle  = data[i][COL.Gen_Title - 1] || data[i][COL.Title - 1] || 'Story Video';
      var genSummary= data[i][COL.Gen_Summary - 1] || '';
      var genTags   = data[i][COL.Gen_Tags - 1] || '';
      var thumbLink = data[i][COL.DriveImg_Link - 1] || '';

      Logger.log('[trigger] Uploading row ' + rowNum + ': ' + genTitle);

      uploadToYouTube({
        rowNum:       rowNum,
        driveUrl:     driveLink,
        title:        genTitle,
        description:  genSummary,
        privacy:      'public',
        tags:         genTags,
        accountEmail: accountEmail,
        thumbnailUrl: thumbLink
      });
    }
  }
}


// ─────────────────────────────────────────────────────────────────────────────
// ACCOUNT MANAGEMENT
// ─────────────────────────────────────────────────────────────────────────────

/**
 * getAccounts — returns list of registered accounts with token status
 */
function getAccounts() {
  var props    = PropertiesService.getScriptProperties().getProperties();
  var accounts = [];

  // Scan Script Properties for TOKEN_ keys
  for (var key in props) {
    if (key.indexOf(TOKEN_PREFIX) === 0) {
      var email = key.substring(TOKEN_PREFIX.length);
      var token = {};
      try { token = JSON.parse(props[key]); } catch(e) {}

      accounts.push({
        email:     email,
        hasToken:  !!props[key],
        tokenAge:  token.saved_at || 'unknown',
        channel:   token.channel  || '',
        channelId: token.channelId|| ''
      });
    }
  }

  // Also include accounts registered via addAccount even without tokens yet
  var regKey = 'REGISTERED_ACCOUNTS';
  var regRaw = PropertiesService.getScriptProperties().getProperty(regKey);
  var registered = regRaw ? JSON.parse(regRaw) : [];

  registered.forEach(function(acc) {
    var already = accounts.some(function(a) { return a.email === acc.email; });
    if (!already) {
      accounts.push({
        email:     acc.email,
        hasToken:  false,
        tokenAge:  '',
        channel:   acc.channel   || '',
        channelId: acc.channelId || ''
      });
    }
  });

  return { success: true, accounts: accounts };
}

/**
 * addAccount — registers a new account email
 * Params: { email, channel, channelId }
 * User must then open the OAuth URL in browser to authorize
 */
function addAccount(params) {
  if (!params.email) return { success: false, error: 'email required' };

  var regKey     = 'REGISTERED_ACCOUNTS';
  var props      = PropertiesService.getScriptProperties();
  var regRaw     = props.getProperty(regKey);
  var registered = regRaw ? JSON.parse(regRaw) : [];

  // Check if already registered
  var exists = registered.some(function(a) { return a.email === params.email; });
  if (!exists) {
    registered.push({
      email:     params.email,
      channel:   params.channel   || '',
      channelId: params.channelId || ''
    });
    props.setProperty(regKey, JSON.stringify(registered));
  }

  // Return the OAuth URL the user must open to authorize this account
  var authUrl = _getOAuthUrl(params.email);
  _writeLog('ADD_ACCOUNT', params.email, 'Channel: ' + (params.channel || ''));
  return { success: true, email: params.email, authUrl: authUrl };
}

/**
 * removeAccount — removes an account and its token from Script Properties
 * Params: { email }
 */
function removeAccount(params) {
  if (!params.email) return { success: false, error: 'email required' };

  var props  = PropertiesService.getScriptProperties();

  // Remove token
  props.deleteProperty(TOKEN_PREFIX + params.email);

  // Remove from registered list
  var regKey     = 'REGISTERED_ACCOUNTS';
  var regRaw     = props.getProperty(regKey);
  var registered = regRaw ? JSON.parse(regRaw) : [];
  registered     = registered.filter(function(a) { return a.email !== params.email; });
  props.setProperty(regKey, JSON.stringify(registered));

  _writeLog('REMOVE_ACCOUNT', params.email, 'Account removed');
  return { success: true, email: params.email };
}

/**
 * deauthAccount — clears only the OAuth token (keeps account registered)
 * User will need to re-authorize by opening OAuth URL again
 * Params: { email }
 */
function deauthAccount(params) {
  if (!params.email) return { success: false, error: 'email required' };

  var props = PropertiesService.getScriptProperties();
  props.deleteProperty(TOKEN_PREFIX + params.email);

  // Return new auth URL so user can re-authorize immediately
  var authUrl = _getOAuthUrl(params.email);
  _writeLog('DEAUTH', params.email, 'Token cleared — re-auth required');
  return { success: true, email: params.email, authUrl: authUrl, message: 'Token cleared. Open authUrl to re-authorize.' };
}

/**
 * _getOAuthUrl — generates the Apps Script Web App URL with email as state param
 * User opens this URL in their browser to start OAuth flow
 */
function _getOAuthUrl(email) {
  // ScriptApp.getService().getUrl() returns the deployed Web App URL
  try {
    var url = ScriptApp.getService().getUrl();
    return url + '?auth=' + encodeURIComponent(email);
  } catch (e) {
    return 'https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec?auth=' + encodeURIComponent(email);
  }
}

/**
 * _handleOAuthCallback — processes OAuth ?code= callback
 * Called by doGet when browser redirects back after Google login
 */
function _handleOAuthCallback(e) {
  // For Apps Script's built-in YouTube service, OAuth is handled automatically
  // This function saves the email → channel mapping for reference
  var email = e.parameter.auth || e.parameter.state || '';

  try {
    // Verify YouTube access by reading channel info
    var channels = YouTube.Channels.list('snippet', { mine: true });
    var channel  = channels.items && channels.items.length > 0 ? channels.items[0] : null;
    var channelName = channel ? channel.snippet.title : '';
    var channelId   = channel ? channel.id : '';

    // Save token info to Script Properties
    var tokenData = {
      email:     email,
      channel:   channelName,
      channelId: channelId,
      saved_at:  new Date().toISOString()
    };
    PropertiesService.getScriptProperties().setProperty(
      TOKEN_PREFIX + email,
      JSON.stringify(tokenData)
    );

    _writeLog('AUTH_SUCCESS', email, 'Channel: ' + channelName + ' (' + channelId + ')');

    return HtmlService.createHtmlOutput(
      '<h2 style="font-family:sans-serif;color:#00CC66">✅ Authorization Successful!</h2>' +
      '<p>Account: <b>' + email + '</b></p>' +
      '<p>Channel: <b>' + channelName + '</b> (' + channelId + ')</p>' +
      '<p>You can close this tab and return to the dashboard.</p>'
    );
  } catch (err) {
    return HtmlService.createHtmlOutput(
      '<h2 style="color:red">❌ Authorization Failed</h2>' +
      '<p>' + err.toString() + '</p>'
    );
  }
}


// ─────────────────────────────────────────────────────────────────────────────
// ANALYTICS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * getAnalytics — fetch YouTube stats for a single video
 * Params: { videoId }
 * Returns: { views, likes, comments, title, publishedAt, thumbnailUrl }
 */
function getAnalytics(params) {
  if (!params.videoId) return { success: false, error: 'videoId required' };

  try {
    var resp = YouTube.Videos.list('statistics,snippet', { id: params.videoId });
    if (!resp.items || resp.items.length === 0) {
      return { success: false, error: 'Video not found: ' + params.videoId };
    }

    var item  = resp.items[0];
    var stats = item.statistics || {};
    var snip  = item.snippet    || {};

    return {
      success:      true,
      videoId:      params.videoId,
      title:        snip.title           || '',
      publishedAt:  snip.publishedAt     || '',
      thumbnailUrl: (snip.thumbnails && snip.thumbnails.medium) ? snip.thumbnails.medium.url : '',
      views:        parseInt(stats.viewCount    || 0),
      likes:        parseInt(stats.likeCount    || 0),
      comments:     parseInt(stats.commentCount || 0),
      favorites:    parseInt(stats.favoriteCount|| 0)
    };
  } catch (err) {
    return { success: false, error: err.toString() };
  }
}

/**
 * getAllAnalytics — fetch stats for ALL rows that have a YouTube ID
 * Returns aggregated totals + per-video breakdown
 */
function getAllAnalytics() {
  var ws   = _getSheet();
  var data = ws.getDataRange().getValues();
  var videos = [];

  // Collect all rows with YouTube IDs
  for (var i = 1; i < data.length; i++) {
    var ytId = data[i][COL.YouTube_ID - 1];
    if (ytId) {
      videos.push({
        rowNum:  i + 1,
        videoId: ytId,
        title:   data[i][COL.Gen_Title - 1] || data[i][COL.Title - 1] || '',
        ytUrl:   data[i][COL.YouTube_URL - 1] || 'https://youtu.be/' + ytId
      });
    }
  }

  // Fetch stats in batches of 50 (YouTube API limit per request)
  var results    = [];
  var totalViews = 0, totalLikes = 0, totalComments = 0;

  for (var b = 0; b < videos.length; b += 50) {
    var batch   = videos.slice(b, b + 50);
    var ids     = batch.map(function(v) { return v.videoId; }).join(',');

    try {
      var resp = YouTube.Videos.list('statistics,snippet', { id: ids });
      if (resp.items) {
        resp.items.forEach(function(item) {
          var stats = item.statistics || {};
          var snip  = item.snippet    || {};
          var v     = parseInt(stats.viewCount    || 0);
          var l     = parseInt(stats.likeCount    || 0);
          var c     = parseInt(stats.commentCount || 0);
          totalViews    += v;
          totalLikes    += l;
          totalComments += c;

          // Match back to our row info
          var meta = batch.find(function(bv) { return bv.videoId === item.id; }) || {};
          results.push({
            rowNum:      meta.rowNum    || 0,
            videoId:     item.id,
            title:       snip.title    || meta.title || '',
            publishedAt: snip.publishedAt || '',
            ytUrl:       meta.ytUrl    || 'https://youtu.be/' + item.id,
            thumbnailUrl:(snip.thumbnails && snip.thumbnails.medium) ? snip.thumbnails.medium.url : '',
            views:       v,
            likes:       l,
            comments:    c
          });
        });
      }
    } catch (batchErr) {
      Logger.log('[analytics] Batch error: ' + batchErr);
    }
  }

  // Sort by views descending
  results.sort(function(a, b) { return b.views - a.views; });

  return {
    success:       true,
    total_videos:  results.length,
    total_views:   totalViews,
    total_likes:   totalLikes,
    total_comments:totalComments,
    videos:        results
  };
}


// ─────────────────────────────────────────────────────────────────────────────
// UPLOAD LOG
// ─────────────────────────────────────────────────────────────────────────────

/**
 * getLogs — returns recent log entries from UploadLog sheet
 * Params: { limit } (default 100)
 */
function getLogs(params) {
  var limit = (params && params.limit) ? parseInt(params.limit) : 100;
  var logWs = _getLogSheet();
  var data  = logWs.getDataRange().getValues();

  // Skip header, take last N rows, reverse for newest-first
  var rows = data.slice(1).reverse().slice(0, limit).map(function(r) {
    return {
      timestamp: r[0] || '',
      type:      r[1] || '',
      target:    r[2] || '',
      detail:    r[3] || ''
    };
  });

  return { success: true, logs: rows, total: data.length - 1 };
}

/**
 * clearLogs — clears all log entries (keeps header row)
 */
function clearLogs() {
  var logWs  = _getLogSheet();
  var lastRow = logWs.getLastRow();
  if (lastRow > 1) {
    logWs.deleteRows(2, lastRow - 1);
  }
  return { success: true };
}

/**
 * _writeLog — internal helper to append a log entry
 */
function _writeLog(type, target, detail) {
  try {
    var logWs = _getLogSheet();
    var now   = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss');
    logWs.appendRow([now, type, target, detail]);
  } catch (e) {
    Logger.log('[log error] ' + e);
  }
}


// ─────────────────────────────────────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────────────────────────────────────

/**
 * getConfig — returns saved config values
 */
function getConfig() {
  var props = PropertiesService.getScriptProperties();
  return {
    success:   true,
    sheetId:   props.getProperty('CONFIG_SHEET_ID')   || SHEET_ID,
    sheetName: props.getProperty('CONFIG_SHEET_NAME')  || SHEET_NAME,
    timezone:  props.getProperty('CONFIG_TIMEZONE')    || Session.getScriptTimeZone(),
    maxPerDay: props.getProperty('CONFIG_MAX_PER_DAY') || '5',
    defaultPrivacy: props.getProperty('CONFIG_DEFAULT_PRIVACY') || 'public',
    defaultCategory: props.getProperty('CONFIG_DEFAULT_CATEGORY') || '27'
  };
}

/**
 * saveConfig — saves config values to Script Properties
 * Params: { sheetId, sheetName, timezone, maxPerDay, defaultPrivacy, defaultCategory }
 */
function saveConfig(params) {
  var props = PropertiesService.getScriptProperties();
  if (params.sheetId)          props.setProperty('CONFIG_SHEET_ID',          params.sheetId);
  if (params.sheetName)        props.setProperty('CONFIG_SHEET_NAME',        params.sheetName);
  if (params.timezone)         props.setProperty('CONFIG_TIMEZONE',          params.timezone);
  if (params.maxPerDay)        props.setProperty('CONFIG_MAX_PER_DAY',       params.maxPerDay);
  if (params.defaultPrivacy)   props.setProperty('CONFIG_DEFAULT_PRIVACY',   params.defaultPrivacy);
  if (params.defaultCategory)  props.setProperty('CONFIG_DEFAULT_CATEGORY',  params.defaultCategory);

  _writeLog('CONFIG', 'saveConfig', 'Settings updated');
  return { success: true };
}


// ─────────────────────────────────────────────────────────────────────────────
// INTERNAL HELPERS
// ─────────────────────────────────────────────────────────────────────────────

/** Returns the main story data worksheet */
function _getSheet() {
  var ss = SpreadsheetApp.openById(SHEET_ID || _getProp('CONFIG_SHEET_ID'));
  return ss.getSheetByName(SHEET_NAME) || ss.getSheets()[0];
}

/** Returns (or creates) the UploadLog worksheet */
function _getLogSheet() {
  var ss = SpreadsheetApp.openById(SHEET_ID || _getProp('CONFIG_SHEET_ID'));
  var ws = ss.getSheetByName(LOG_SHEET);
  if (!ws) {
    // Create log sheet with headers
    ws = ss.insertSheet(LOG_SHEET);
    ws.appendRow(['Timestamp', 'Type', 'Target', 'Detail']);
    ws.getRange('1:1').setFontWeight('bold');
    ws.setFrozenRows(1);
  }
  return ws;
}

/** Shortcut to read a Script Property */
function _getProp(key) {
  return PropertiesService.getScriptProperties().getProperty(key) || '';
}

/** Returns JSON ContentService output with CORS header */
function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * _extractDriveId — extracts file ID from any Google Drive URL format
 * Handles: /file/d/{ID}/, ?id={ID}, /d/{ID}
 */
function _extractDriveId(url) {
  var patterns = [
    /\/file\/d\/([a-zA-Z0-9_-]{20,})/,
    /[?&]id=([a-zA-Z0-9_-]{20,})/,
    /\/d\/([a-zA-Z0-9_-]{20,})/
  ];
  for (var i = 0; i < patterns.length; i++) {
    var m = url.match(patterns[i]);
    if (m) return m[1];
  }
  return null;
}

/**
 * authorizeYouTube — run this manually ONCE from Apps Script editor
 * to grant YouTube API access for the primary account
 */
function authorizeYouTube() {
  var check = YouTube.Channels.list('snippet', { mine: true });
  Logger.log('Channels: ' + JSON.stringify(check.items && check.items[0] && check.items[0].snippet));
  Logger.log('Authorization successful!');
}

/**
 * setupTrigger — run manually once to create the hourly auto-upload trigger
 * This checks scheduled uploads every hour and uploads when time arrives
 */
function setupTrigger() {
  // Remove existing triggers for autoUploadTrigger to avoid duplicates
  ScriptApp.getProjectTriggers().forEach(function(t) {
    if (t.getHandlerFunction() === 'autoUploadTrigger') {
      ScriptApp.deleteTrigger(t);
    }
  });
  // Create new hourly trigger
  ScriptApp.newTrigger('autoUploadTrigger')
    .timeBased()
    .everyHours(1)
    .create();
  Logger.log('Hourly trigger set for autoUploadTrigger');
}

/**
 * clearAllTokens — removes all stored OAuth tokens for deauthorization
 * Run this function manually to clear all YouTube authorizations
 */
function clearAllTokens() {
  var props = PropertiesService.getScriptProperties();
  var keys = props.getKeys();
  var cleared = 0;
  
  keys.forEach(function(key) {
    if (key.indexOf('TOKEN_') === 0) {
      props.deleteProperty(key);
      cleared++;
    }
  });
  
  Logger.log('Cleared ' + cleared + ' OAuth tokens');
  return { success: true, cleared: cleared };
}

/**
 * testAuthorization — verifies current YouTube authorization status
 */
function testAuthorization() {
  try {
    var channels = YouTube.Channels.list('snippet', { mine: true });
    var channel = channels.items && channels.items.length > 0 ? channels.items[0] : null;
    
    if (channel) {
      Logger.log('Authorization successful!');
      Logger.log('Channel: ' + channel.snippet.title);
      Logger.log('Channel ID: ' + channel.id);
      return { 
        success: true, 
        channel: channel.snippet.title,
        channelId: channel.id,
        subscribers: channel.statistics ? channel.statistics.subscriberCount : 'N/A'
      };
    } else {
      Logger.log('No channels found - authorization may be incomplete');
      return { success: false, error: 'No channels found' };
    }
  } catch (err) {
    Logger.log('Authorization test failed: ' + err.toString());
    return { success: false, error: err.toString() };
  }
}

/**
 * forceReauthorization — clears tokens and triggers fresh authorization
 */
function forceReauthorization() {
  Logger.log('Starting force reauthorization process...');
  
  // Step 1: Clear existing tokens
  var clearResult = clearAllTokens();
  Logger.log('Tokens cleared: ' + clearResult.cleared);
  
  // Step 2: Test authorization (this will trigger OAuth flow)
  var authResult = testAuthorization();
  
  if (authResult.success) {
    Logger.log('Reauthorization successful!');
    return authResult;
  } else {
    Logger.log('Reauthorization requires manual OAuth - please run authorizeYouTube()');
    return { 
      success: false, 
      message: 'Please run authorizeYouTube() manually to complete OAuth flow',
      error: authResult.error 
    };
  }
}