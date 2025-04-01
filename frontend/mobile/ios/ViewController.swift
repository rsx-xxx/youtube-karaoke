//
//  ViewController.swift
//  YouTubeKaraoke
//
//  Created by You on 2025-03-31.
//

import UIKit
import AVKit

class ViewController: UIViewController {

    private var player: AVPlayer?
    private var playerLayer: AVPlayerLayer?
    private var lyricsLabel: UILabel = {
        let label = UILabel()
        label.textAlignment = .center
        label.textColor = UIColor.systemGreen
        label.font = UIFont.systemFont(ofSize: 24, weight: .bold)
        label.backgroundColor = UIColor.black.withAlphaComponent(0.4)
        label.numberOfLines = 0
        label.translatesAutoresizingMaskIntoConstraints = false
        return label
    }()

    // Example transcript data
    private let segments: [Segment] = [
        Segment(start: 0.0, end: 5.0, text: "Instrumental intro..."),
        Segment(start: 5.0, end: 10.0, text: "First line of lyrics"),
        Segment(start: 10.0, end: 15.0, text: "Second line of lyrics")
    ]

    private var timeObserver: Any?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        setupPlayer()
        setupLyricsLabel()
    }

    private func setupPlayer() {
        // Replace with your processed karaoke video URL
        guard let url = URL(string: "http://YOUR_SERVER_URL/processed/example_karaoke.mp4") else {
            return
        }
        player = AVPlayer(url: url)
        playerLayer = AVPlayerLayer(player: player)
        guard let playerLayer = playerLayer else { return }

        playerLayer.frame = view.bounds
        playerLayer.videoGravity = .resizeAspect
        view.layer.addSublayer(playerLayer)

        // Add time observer for karaoke sync
        let interval = CMTime(seconds: 0.5, preferredTimescale: CMTimeScale(NSEC_PER_SEC))
        timeObserver = player?.addPeriodicTimeObserver(forInterval: interval, queue: .main) { [weak self] currentTime in
            self?.updateLyrics(time: currentTime.seconds)
        }

        player?.play()
    }

    private func setupLyricsLabel() {
        view.addSubview(lyricsLabel)
        NSLayoutConstraint.activate([
            lyricsLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            lyricsLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            lyricsLabel.bottomAnchor.constraint(equalTo: view.bottomAnchor, constant: -50),
            lyricsLabel.heightAnchor.constraint(equalToConstant: 60)
        ])
    }

    private func updateLyrics(time: Double) {
        // Find which segment the current time falls into
        let currentSegment = segments.first { seg in
            return time >= seg.start && time <= seg.end
        }
        lyricsLabel.text = currentSegment?.text ?? ""
    }

    deinit {
        if let observer = timeObserver {
            player?.removeTimeObserver(observer)
        }
    }
}

struct Segment {
    let start: Double
    let end: Double
    let text: String
}