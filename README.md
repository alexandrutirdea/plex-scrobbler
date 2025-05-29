# plex-scrobbler
Docker scrobbler for Plex

This project stemmed from the fact that the scrobbling option offered by Plex is very limited. It had issues detecting repeats, sometimes failed to scrobble songs entirely. This is a solution made up from two Python scripts: one that sends now playing notifications to Last.fm, one that tracks the playing songs on Plex and submits the scrobbles. They could have been part of the same script, but I prefer this level of separation. Once the docker container is built, it just works.
