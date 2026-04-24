/**
 * Bright Little Stories — Apps Script Backend
 * Serves index.html with a simple clean REST API
 */

var SHEET_ID   = '1p5sg2j-6IZhbj-7s2giJM_9e9rWnK-ixgcrt3jgR7Gc'; // Replace if needed via Config
var SHEET_NAME = 'Database';

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
  YouTube_ID:     18,   // R
  YouTube_URL:    19,   // S
  Schedule_Time:  20,   // T
  YT_Status:      21    // U
};

function _getSheet() {
  var ss = SpreadsheetApp.openById(SHEET_ID);
  return ss.getSheetByName(SHEET_NAME) || ss.getSheets()[0];
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON)
    .setHeader("Access-Control-Allow-Origin", "*");
}

function doGet(e) {
  var action = e.parameter.action;
  if (action === 'getStories') {
    return _json(getStories());
  }
  return ContentService.createTextOutput("Bright Little Stories API OK");
}

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var action = data.action;

    if (!action) {
      return _json(addStory(data));
    } else if (action === 'updateStatus') {
      return _json(updateStatus(data));
    } else if (action === 'updateYTStatus') {
      return _json(updateYTStatus(data));
    } else if (action === 'saveFileUrl') {
      return _json(saveFileUrl(data));
    } else if (action === 'saveYouTubeResult') {
      return _json(saveYouTubeResult(data));
    }

    return _json({ error: "Unknown action" });
  } catch (err) {
    return _json({ error: err.toString() });
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// ENDPOINTS
// ─────────────────────────────────────────────────────────────────────────────

function getStories() {
  var ws = _getSheet();
  var data = ws.getDataRange().getValues();
  var stories = [];
  
  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    var storyText = row[COL.Story - 1] || '';
    
    var wc = 0;
    if (storyText) {
      var words = storyText.toString().trim().split(/\s+/);
      if (words.length > 0 && words[0] !== '') wc = words.length;
    }
    
    stories.push({
      "Status": row[COL.Status - 1] || '',
      "Theme": row[COL.Theme - 1] || '',
      "Title": row[COL.Title - 1] || '',
      "Story Text": storyText,
      "Moral": row[COL.Moral - 1] || '',
      "Hashtags": row[COL.Gen_Tags - 1] || '',
      "Date": row[COL.Created_Time - 1] || '',
      "Word Count": wc,
      "Drive Thumbnail URL": row[COL.DriveImg_Link - 1] || '',
      "Drive Video URL": row[COL.Drive_Link - 1] || '',
      "YouTube URL": row[COL.YouTube_URL - 1] || '',
      "YT_Status": row[COL.YT_Status - 1] || ''
    });
  }
  
  return { stories: stories };
}

function addStory(data) {
  var ws = _getSheet();
  var newRow = new Array(21).fill('');
  
  newRow[COL.Status - 1] = data.status || 'Generated';
  newRow[COL.Theme - 1] = data.theme || '';
  newRow[COL.Title - 1] = data.title || '';
  newRow[COL.Story - 1] = data.storyText || '';
  newRow[COL.Moral - 1] = data.moral || '';
  newRow[COL.Gen_Tags - 1] = data.hashtags || '';
  newRow[COL.Created_Time - 1] = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'MM/dd/yyyy hh:mm a');
  
  // Insert at Row 2 so it pushes everything down
  ws.insertRowAfter(1);
  ws.getRange(2, 1, 1, newRow.length).setValues([newRow]);
  
  return { success: true };
}

function updateStatus(data) {
  var ws = _getSheet();
  ws.getRange(data.storyRow, COL.Status).setValue(data.status);
  return { success: true };
}

function updateYTStatus(data) {
  var ws = _getSheet();
  ws.getRange(data.storyRow, COL.YT_Status).setValue(data.ytStatus);
  return { success: true };
}

function saveFileUrl(data) {
  var ws = _getSheet();
  if (data.urlField === 'thumbnailUrl') {
    ws.getRange(data.storyRow, COL.DriveImg_Link).setValue(data.url);
  } else if (data.urlField === 'videoUrl') {
    ws.getRange(data.storyRow, COL.Drive_Link).setValue(data.url);
  }
  return { success: true };
}

function saveYouTubeResult(data) {
  var ws = _getSheet();
  ws.getRange(data.storyRow, COL.YouTube_ID).setValue(data.videoId);
  ws.getRange(data.storyRow, COL.YouTube_URL).setValue(data.youtubeUrl);
  ws.getRange(data.storyRow, COL.Status).setValue('Published');
  return { success: true };
}