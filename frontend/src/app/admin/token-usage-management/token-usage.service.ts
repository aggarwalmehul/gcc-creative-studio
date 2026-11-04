/**
 * Copyright 2026 Google LLC
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

import {Injectable} from '@angular/core';
import {HttpClient, HttpErrorResponse} from '@angular/common/http';
import {Observable, throwError} from 'rxjs';
import {catchError} from 'rxjs/operators';
import {environment} from '../../../environments/environment';

export interface TokenUsageRow {
  timestamp: string;
  platform: string;
  userEmail: string;
  model: string;
  total: number;
}

@Injectable({
  providedIn: 'root',
})
export class TokenUsageService {
  private apiUrl = `${environment.backendURL}/admin/token-usage`;

  constructor(private http: HttpClient) {}

  // TOKEN_USAGE_ADMIN_PAGE_V1: a first, simple read-only view over the
  // shared BigQuery usage table. Grouping/charts/cost estimates deferred
  // to a later iteration.
  getTokenUsage(days = 7): Observable<TokenUsageRow[]> {
    return this.http
      .get<TokenUsageRow[]>(`${this.apiUrl}?days=${days}`)
      .pipe(catchError(this.handleError));
  }

  private handleError(error: HttpErrorResponse) {
    let errorMessage = 'An unknown error occurred!';
    if (error.error instanceof ErrorEvent) {
      errorMessage = `Error: ${error.error.message}`;
    } else {
      errorMessage = `Error Code: ${error.status}\nMessage: ${error.message}`;
      if (error.error && typeof error.error === 'object' && error.error.detail) {
        errorMessage += `\nDetails: ${JSON.stringify(error.error.detail)}`;
      } else if (error.error) {
        errorMessage += `\nBackend Error: ${JSON.stringify(error.error)}`;
      }
    }
    console.error(errorMessage);
    return throwError(() => new Error(errorMessage));
  }
}
