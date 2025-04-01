/*
  Content script that injects a karaoke overlay into YouTube's player.
  Communicates with the Karaoke backend to fetch transcripts for the current video ID.
  Demonstration only; real logic would detect the YouTube video ID and call the /process endpoint.
*/

(function () {
  console.log("YouTube Karaoke Extension loaded.");

  // Create overlay
  const karaokeDiv = document.createElement("div");
  karaokeDiv.id = "karaoke-extension-overlay";
  karaokeDiv.style.position = "absolute";
  karaokeDiv.style.bottom = "60px";
  karaokeDiv.style.width = "100%";
  karaokeDiv.style.textAlign = "center";
  karaokeDiv.style.color = "#00ff88";
  karaokeDiv.style.fontSize = "24px";
  karaokeDiv.style.textShadow = "2px 2px 8px black";
  karaokeDiv.style.pointerEvents = "none";
  karaokeDiv.style.zIndex = "999999";

  // We attempt to append it to the YouTube player container
  const player = document.getElementById("movie_player") || document.body;
  player.appendChild(karaokeDiv);

  // In a real scenario:
  // 1. Parse the current video ID from URL (e.g. new URL(location.href).searchParams.get("v"))
  // 2. Call the backend (/process) with that ID.
  // 3. Stream the final karaoke or just get the transcript if you prefer an overlay approach.

  karaokeDiv.innerText = "Karaoke lyrics will appear here...";
})();