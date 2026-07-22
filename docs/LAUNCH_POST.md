# Project Launch Post

I came back from a Bali vacation with my engineering friends and 1,004 photos and videos.

Not just from my phone, but from my GoPro, tour companies, and friends.

 

Like every trip, I wanted Instagram reels, a photo album, highlight videos, and a documentary.

 

Instead, I had a folder full of media that I knew I'd probably never organize.

 

That made me wonder:

 Could AI turn a messy vacation folder into something that actually tells a story? followed by another question 

 With today's AI coding tools, could I design and build a real product in under a week?

 

So during my vacation, spending just a few hours each day, I built the first version of MemoryCurator using OpenAI Codex and nothing more than a $100 subscription.

 

The goal wasn't simply to organize files.

 It had to understand memories.

 

That meant:

• Detecting duplicates and near-duplicates.

• Scoring photos and videos differently.

• Grouping media into meaningful moments.

• Automatically creating albums, Instagram reels, and documentary-style videos.

 

The hardest part wasn't finding clips. It was understanding the story. 

 

• A rafting reel shouldn't miss the biggest rapids.

• An ATV reel shouldn't miss the tunnel, mud, water crossings, or the final laughs.

• Albums should prioritize emotion.

• Reels should prioritize energy.

 • Documentaries should prioritize storytelling.

 

That became the real product challenge: 

How do you teach software what a memory is actually for?

 

Under the hood I built it with Python, OpenCV, FFmpeg, ImageHash, YAML configuration, and an architecture designed to plug in AI services like OpenAI Vision and Whisper when deeper understanding is needed.

 

AI helped me build incredibly fast. But it didn't replace product thinking.

 

I still had to decide:

• What should be deterministic?

• What should AI decide?

• What should be configurable?

• How do you avoid creating a black box?

 

My biggest takeaway:

 

AI doesn't replace product thinking.

It amplifies it.

 

I've included the architecture diagram below.

 

I'll also be publishing the complete architecture, implementation details, and GitHub repository soon for anyone interested in building something similar.

 

If you could build one AI product to automate something in your own life, what would it be?

 

P.S. In the spirit of this post, I also used an LLM to polish the writing. The ideas, architecture, and implementation are entirely my own.

 

#AI #OpenAICodex #SoftwareArchitecture #Python #ProductDesign #GenerativeAI
