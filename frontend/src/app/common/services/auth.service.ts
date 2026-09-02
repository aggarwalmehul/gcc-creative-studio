/**
 * Copyright 2025 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {Injectable, PLATFORM_ID, inject} from '@angular/core';
import {Router} from '@angular/router';
import {UserModel, UserRolesEnum} from '../models/user.model';
import {HttpClient, HttpHeaders, HttpErrorResponse} from '@angular/common/http';
import {environment} from '../../../environments/environment';
import {Auth, IdTokenResult} from '@angular/fire/auth';
import {UserService} from '../services/user.service';
import {
  GoogleAuthProvider,
  signInWithPopup,
  UserCredential,
} from '@angular/fire/auth';
import {Observable, from, throwError, of} from 'rxjs';
import {catchError, tap, map, switchMap} from 'rxjs/operators';
import {isPlatformBrowser} from '@angular/common';

// Declare the 'google' global object from the Google Identity Services script
declare const google: any;

const FIREBASE_SESSION_KEY = 'firebase_session';
const USER_DETAILS = 'USER_DETAILS';
const LOGIN_ROUTE = '/login';

interface FirebaseSession {
  token: string;
  expiry: number; // Expiration timestamp in milliseconds
}

@Injectable({
  providedIn: 'root',
})
export class AuthService {
  private readonly auth: Auth = inject(Auth);
  private platformId = inject(PLATFORM_ID);
  private readonly provider: GoogleAuthProvider = new GoogleAuthProvider();

  // Store token temporarily in memory for the session
  private currentOAuthAccessToken: string | null = null;
  private firebaseIdToken: string | null = null; // To store the Firebase token for the test
  private firebaseTokenExpiry: number | null = null; // To store token expiration time (in ms)

  constructor(
    private router: Router,
    private httpClient: HttpClient,
    private userService: UserService,
  ) {
    this.provider.setCustomParameters({
      // Set custom params for the provider
      prompt: 'select_account',
    });
    this.loadSessionFromStorage();
  }

  /**
   * A test sign-in method to get a Google ID token compatible with Firebase.
   *
   * @returns An Observable that emits the Firebase-compatible ID token.
   */
  signInWithGoogleFirebase(): Observable<string> {
    return from(signInWithPopup(this.auth, this.provider)).pipe(
      // Step 1: Get the Firebase ID token from the successful sign-in.
      switchMap((userCredential: UserCredential) => {
        if (!userCredential.user) {
          return throwError(
            () => new Error('Firebase user not found after sign-in.'),
          );
        }
        return from(userCredential.user.getIdTokenResult());
      }),
      // Step 2: Save the session and sync with the backend.
      switchMap((idTokenResult: IdTokenResult) => {
        const token = idTokenResult.token;
        const expirationTime = Date.parse(idTokenResult.expirationTime);

        // Save session details to memory and local storage.
        this.firebaseIdToken = token;
        this.firebaseTokenExpiry = expirationTime;
        const session: FirebaseSession = {token, expiry: expirationTime};
        localStorage.setItem(FIREBASE_SESSION_KEY, JSON.stringify(session));

        // Call the backend to get or create the user profile.
        return this.syncUserWithBackend$(token).pipe(
          map(() => token), // Pass the token along for the final result.
        );
      }),
      catchError((error: any) => {
        console.error('An error occurred during the sign-in process:', error);
        return throwError(
          () => new Error(`Sign-in failed. Please try again. ${error}`),
        );
      }),
    );
  }

  /**
   * Asynchronously gets a valid Firebase token.
   * 1. Checks for a valid, non-expired token in memory/cache.
   * 2. If expired or missing, attempts a silent refresh.
   * 3. If silent refresh fails, it emits an error, signaling a required re-login.
   */
  /**
   * @deprecated Not called anywhere in the app (the AuthInterceptor uses
   * getValidIdentityPlatformToken$ instead). Kept as a thin delegate, rather
   * than removed outright, so the two can never silently drift apart again
   * the way they previously did -- see TOKEN_REFRESH_FIX_V1.
   */
  getValidFirebaseToken$(): Observable<string> {
    return this.getValidIdentityPlatformToken$();
  }

  /**
   * A test sign-in method to get a Google ID token compatible with Identity Platform.
   *
   * @returns An Observable that emits the Identity Platform-compatible ID token.
   */
  signInForGoogleIdentityPlatform(): Observable<string> {
    return this.promptForIdentityPlatformToken$().pipe(
      switchMap(idToken => {
        const payload = JSON.parse(atob(idToken.split('.')[1]));
        const userEmail = payload.email?.toLowerCase();

        // If allowed, proceed to save session and return token
        this.firebaseIdToken = idToken;
        this.firebaseTokenExpiry = payload.exp * 1000;

        const session: FirebaseSession = {
          token: idToken,
          expiry: this.firebaseTokenExpiry,
        };
        localStorage.setItem(FIREBASE_SESSION_KEY, JSON.stringify(session));

        // Call the backend to get or create the user profile.
        return this.syncUserWithBackend$(idToken).pipe(
          map(() => idToken), // Pass the token along for the final result.
        );
      }),
    );
  }

  private promptForIdentityPlatformToken$(): Observable<string> {
    const GOOGLE_CLIENT_ID = environment.GOOGLE_CLIENT_ID;

    return new Observable<string>(observer => {
      if (typeof google === 'undefined') {
        return observer.error(
          new Error(
            'Google Identity Services script not loaded. Add it to index.html',
          ),
        );
      }

      const loginTimeout = setTimeout(() => {
        observer.error(
          new Error(
            'Login timed out or third party sign-in may be disabled. Please try again and enable third party sign-in by clicking on the information button at the top left side of the browser.',
          ),
        );
      }, 15000);

      try {
        google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: (response: any) => {
            clearTimeout(loginTimeout);
            const idToken = response.credential;
            if (idToken) {
              observer.next(idToken);
              observer.complete();
            } else {
              observer.error(
                new Error(
                  'Google Sign-In response did not contain a credential.',
                ),
              );
            }
          },
        });

        // Trigger the One Tap prompt.
        // Per new docs, we don't use the notification object for flow control.
        google.accounts.id.prompt();
      } catch (error) {
        clearTimeout(loginTimeout);
        console.error(
          'Error during Google Identity Platform sign-in initialization:',
          error,
        );
        observer.error(error);
      }
    });
  }

  /**
   * Asynchronously gets a valid Identity Platform token.
   * 1. Checks for a valid, non-expired token in memory/cache.
   * 2. If expired or missing, attempts a silent refresh.
   * 3. If silent refresh fails, it emits an error, signaling a required re-login.
   */
  getValidIdentityPlatformToken$(): Observable<string> {
    // First, check our own session info which is loaded from localStorage.
    // This is synchronous and tells us if we have a valid, non-expired token.
    if (!this.isLoggedIn()) {
      return of();
    }

    // TOKEN_REFRESH_FIX_V1: previously this always returned the possibly-stale
    // cached token below, with no refresh attempt at all -- causing every
    // request to silently reuse an already-expired ID token indefinitely once
    // isLoggedIn() stopped tying "logged in" to the token's own 1-hour expiry
    // (see AUTH_SESSION_TIMEOUT_FIX_V1 below). If the Firebase Auth instance
    // is ready, force a genuine refresh via getIdToken(true), same as
    // getValidFirebaseToken$.
    const currentUser = this.auth.currentUser;
    if (currentUser) {
      return from(currentUser.getIdToken(true)).pipe(
        tap((token: string) => {
          const payload = JSON.parse(atob(token.split('.')[1]));
          const expiry = payload.exp * 1000;

          this.firebaseIdToken = token;
          this.firebaseTokenExpiry = expiry;

          const session: FirebaseSession = {token, expiry};
          localStorage.setItem(FIREBASE_SESSION_KEY, JSON.stringify(session));
        }),
      );
    }

    // Fallback case: The Firebase Auth instance is not yet initialized, but we
    // have a valid token from localStorage. We can use this for the current
    // request. The next request will likely hit the ideal case above.
    return of(this.firebaseIdToken!);
  }

  private syncUserWithBackend$(token: string): Observable<UserModel> {
    const headers = new HttpHeaders().set('Authorization', `Bearer ${token}`);
    return this.httpClient
      .get<UserModel>(`${environment.backendURL}/users/me`, {headers})
      .pipe(
        tap((userDetails: UserModel) => {
          // The backend is the source of truth. Save the returned profile to local storage.
          localStorage.setItem(USER_DETAILS, JSON.stringify(userDetails));
          console.log('User profile successfully synced with backend.');
        }),
        catchError((error: HttpErrorResponse) => {
          console.error('Failed to sync user with backend', error);
          // This is a critical error, so we should propagate it.
          return throwError(
            () =>
              new Error(
                error?.error?.detail ||
                  `Could not synchronize user profile with the server. ${error?.error?.detail}`,
              ),
          );
        }),
      );
  }

  async logout(route: string = LOGIN_ROUTE) {
    return this.auth
      .signOut()
      .then(() => {
        this.currentOAuthAccessToken = null; // Clear stored token on logout
        // Clear Firebase session data
        this.firebaseIdToken = null;
        this.firebaseTokenExpiry = null;
        localStorage.removeItem(FIREBASE_SESSION_KEY);
        localStorage.removeItem(USER_DETAILS);
        localStorage.removeItem('showTooltip');
        void this.router.navigateByUrl(route);
      })
      .catch(e => {
        console.error('Sign Out Error', e);
        localStorage.removeItem(FIREBASE_SESSION_KEY);
        localStorage.removeItem(USER_DETAILS);
        localStorage.removeItem('showTooltip');
        void this.router.navigate([LOGIN_ROUTE]);
      });
  }

  isLoggedIn() {
    if (!isPlatformBrowser(this.platformId)) return false;

    // AUTH_SESSION_TIMEOUT_FIX_V1: previously this checked whether the CACHED ID
    // token's own 1-hour JWT expiry had passed, and treated that as
    // "not logged in" -- which forced a hard logout (via
    // getValidFirebaseToken$ -> AuthInterceptor) roughly every hour,
    // even though Firebase's underlying refresh token was still valid
    // and perfectly capable of silently refreshing the ID token.
    // A Firebase session is considered active if either Firebase's own
    // restored currentUser exists, or we have a previously-cached
    // token. The short-lived ID token's staleness is a separate concern,
    // handled by getValidFirebaseToken$() via a genuine refresh
    // (currentUser.getIdToken(true)); only a REAL refresh failure there
    // (e.g. a revoked refresh token) should result in logout.
    // This method also no longer navigates as a side effect -- callers
    // (route guards) already redirect to LOGIN_ROUTE themselves when
    // this returns false, and having a boolean-returning check trigger
    // navigation on every API call was part of the underlying bug.
    return !!(this.auth.currentUser || this.firebaseIdToken);
  }

  private loadSessionFromStorage(): void {
    if (!isPlatformBrowser(this.platformId)) return;

    const sessionStr = localStorage.getItem(FIREBASE_SESSION_KEY);
    if (sessionStr) {
      const session: FirebaseSession = JSON.parse(sessionStr);
      // Check if the stored session is still valid
      if (session.expiry > Date.now()) {
        this.firebaseIdToken = session.token;
        this.firebaseTokenExpiry = session.expiry;
      } else {
        // If expired, remove it from storage.
        localStorage.removeItem(FIREBASE_SESSION_KEY);
      }
    }
  }

  isUserLoggedIn() {
    if (!isPlatformBrowser(this.platformId)) return false;

    const isUserLoggedIn = localStorage.getItem(FIREBASE_SESSION_KEY) !== null;
    return isUserLoggedIn;
  }

  isUserAdmin() {
    if (!isPlatformBrowser(this.platformId)) return false;

    const user_role = this.userService.getUserDetails()?.roles;
    return user_role?.includes(UserRolesEnum.ADMIN) || false;
  }

  isUserWorkflows() {
    if (!isPlatformBrowser(this.platformId)) return false;

    const user_role = this.userService.getUserDetails()?.roles;
    return user_role?.includes(UserRolesEnum.WORKFLOWS) || false;
  }

  getToken() {
    return this.firebaseIdToken;
  }

  setOAuthAccessToken(token: string | null): void {
    this.currentOAuthAccessToken = token;
  }

  getOAuthAccessToken(): string | null {
    // Renamed from getAccessToken for clarity
    return this.currentOAuthAccessToken;
  }

  /**
   * Retrieves the currently stored access token.
   */
  getAccessToken(): string | null {
    // Note: Tokens expire (usually after 1 hour).
    // A robust implementation would check expiry or refresh the token.
    // Firebase Auth automatically handles ID token refresh, but OAuth access token
    // refresh requires re-authentication or more complex flows not covered here.
    // For a simple deploy button click, getting a fresh token on sign-in might suffice.
    return this.currentOAuthAccessToken;
  }
}
