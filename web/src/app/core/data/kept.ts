import { Observable, ReplaySubject, defer, of, tap } from 'rxjs';

/**
 * An answer fetched once and handed to everyone who asks afterwards.
 *
 * The pages each fetched their own on arrival, so moving between them meant a
 * request, an empty panel and a wait, every time, for a library that had not
 * changed since the last look. On a desktop reached over a tailnet that is a
 * visible stall on a page that already had the answer a moment ago.
 *
 * The first caller starts the request. Anyone arriving while it is in flight
 * waits on the same one rather than starting a second. Anyone arriving after
 * it lands gets the value synchronously, which is what makes a second visit
 * to a page draw immediately rather than flashing its loading state.
 *
 * Nothing here expires on a timer. What invalidates a library is a render
 * finishing or somebody signing out, and both are events this application
 * already knows about, so `forget()` is called at those moments rather than
 * guessed at with an age.
 */
export class Kept<T> {
  private held: T | undefined;
  private inFlight: Observable<T> | null = null;

  constructor(private readonly fetch: () => Observable<T>) {}

  /** The held answer, or the one request everybody shares. */
  get(): Observable<T> {
    // defer, so `held` is read when somebody subscribes rather than when the
    // observable is built. Built once and reused, it would hand out whatever
    // was held at construction for the rest of the session.
    return defer(() => {
      if (this.held !== undefined) {
        return of(this.held);
      }
      if (this.inFlight === null) {
        const shared = new ReplaySubject<T>(1);
        this.inFlight = shared.asObservable();
        this.fetch()
          .pipe(tap({
            // Cleared on failure as well as on success: a refusal must not
            // become the answer every later caller receives.
            error: () => (this.inFlight = null),
          }))
          .subscribe({
            next: (value) => {
              this.held = value;
              shared.next(value);
              shared.complete();
            },
            error: (failure) => {
              this.inFlight = null;
              shared.error(failure);
            },
          });
      }
      return this.inFlight;
    });
  }

  /** Whether an answer is already in hand, so a caller can skip its spinner. */
  get ready(): boolean {
    return this.held !== undefined;
  }

  /** Throw the answer away. The next ask fetches again. */
  forget(): void {
    this.held = undefined;
    this.inFlight = null;
  }
}
