"""The HTTP edge over the song_generator pipeline.

Three front ends are planned over one pipeline: the command line that exists, a
web interface, and a desktop one later. So the work lives in plain modules here
and the FastAPI layer stays thin, because logic written into request handlers
has to be written again for the next front end.

Nothing here imports pipeline internals or changes pipeline behaviour. It reads
what the pipeline writes and runs its entry points the way a person would, so
the pipeline stays the source of truth for what a song sounds like and this
package only answers "what is there" and "how is the run going".
"""
