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

import {Component, ElementRef, Inject, ViewChild} from '@angular/core';
import {
  AudioService,
  CreateAudioDto,
  GenerationModelEnum,
} from '../services/audio/audio.service';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatDialog} from '@angular/material/dialog';
import {OnInit} from '@angular/core';
import {finalize} from 'rxjs';
import {DomSanitizer, SafeResourceUrl} from '@angular/platform-browser';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {JobStatus, MediaItem} from '../common/models/media-item.model';
import {AddVoiceDialogComponent} from '../components/add-voice-dialog/add-voice-dialog.component';
import {
  ImageSelectorComponent,
  MediaItemSelection,
} from '../common/components/image-selector/image-selector.component';
import {SourceAssetResponseDto} from '../common/services/source-asset.service'; // LYRIA_3_PRO_UPGRADE_V1
import {MatIconRegistry} from '@angular/material/icon';
import {LanguageEnum, VoiceEnum} from './audio.constants';
import {SearchService} from '../services/search/search.service';
import {AudioStateService} from '../services/audio-state.service';
import {GalleryService} from '../gallery/gallery.service';
import {Observable} from 'rxjs';
import {
  handleErrorSnackbar,
  handleSuccessSnackbar,
} from '../utils/handleMessageSnackbar';

// UI Helper type
type UiModelType = 'lyria' | 'lyria-3-pro' | 'lyria-3-clip' | 'chirp' | 'gemini-tts'; // LYRIA_3_CLIP_UPGRADE_V1

interface VoiceOption {
  id: VoiceEnum | string; // Allow string for custom cloned voices later
  name: string;
  type: 'preset' | 'custom';
}

interface LanguageOption {
  code: LanguageEnum;
  name: string;
}

// LYRIA_REF_IMAGE_FIX_V1: normalized reference-image shape used by the Lyria 3
// Pro image-to-music feature, regardless of which underlying selector
// result (SourceAssetResponseDto or MediaItemSelection) it came from.
interface ReferenceImageRef {
  kind: 'source_asset' | 'media_item';
  id: number;
  mediaIndex?: number; // only present for kind === 'media_item'
  thumbnailUrl: string;
}

@Component({
  selector: 'app-lyria',
  templateUrl: './audio.component.html',
  styleUrls: ['./audio.component.scss'],
})
export class AudioComponent implements OnInit {
  // UI State
  selectedModel: UiModelType = 'lyria';
  isLoading = false;
  audioUrl: SafeResourceUrl | null = null;

  // Job Tracking
  activeAudioJob$: Observable<MediaItem | null>;
  public readonly JobStatus = JobStatus;
  showErrorOverlay = true;

  // Lyria Specific Inputs
  prompt = '';
  negativePrompt = '';
  seed: number | undefined;
  sampleCount = 1;

  // Lyria 3 Pro Specific Inputs (LYRIA_3_PRO_UPGRADE_V1)
  durationSeconds: number | undefined;
  lyrics = '';
  instrumental = false;
  referenceImageAssets: ReferenceImageRef[] = [];  // LYRIA_REF_IMAGE_FIX_V1

  // TTS & Chirp Specific Inputs
  selectedLanguage: LanguageEnum = LanguageEnum.EN_US;
  selectedVoice: VoiceEnum | string = VoiceEnum.PUCK;

  // GEMINI_3_1_TTS_UPGRADE_V1: lets the user pick which Gemini TTS model to use
  // (Chirp only has one model, so no equivalent dropdown needed there).
  selectedGeminiTtsModel: GenerationModelEnum = GenerationModelEnum.GEMINI_2_5_FLASH_TTS;
  geminiTtsModels: {value: GenerationModelEnum; label: string}[] = [
    {value: GenerationModelEnum.GEMINI_3_1_FLASH_TTS, label: 'Gemini 3.1 Flash TTS (Preview)'},
    {value: GenerationModelEnum.GEMINI_2_5_PRO_TTS, label: 'Gemini 2.5 Pro TTS'},
    {value: GenerationModelEnum.GEMINI_2_5_FLASH_TTS, label: 'Gemini 2.5 Flash TTS'},
    {value: GenerationModelEnum.GEMINI_2_5_FLASH_LITE_PREVIEW_TTS, label: 'Gemini 2.5 Flash Lite TTS (Preview)'},
  ];

  // --- Audio Player State ---
  @ViewChild('audioPlayer') audioPlayerRef!: ElementRef<HTMLAudioElement>;
  isPlaying = false;
  currentTime = '0:00';
  duration = '0:00';
  progressValue = 0;

  mediaItem: MediaItem | null = null;

  languages: LanguageOption[] = [
    {code: LanguageEnum.AR_XA, name: 'Arabic'},
    {code: LanguageEnum.BG_BG, name: 'Bulgarian (Bulgaria)'},
    {code: LanguageEnum.BN_IN, name: 'Bengali (India)'},
    {code: LanguageEnum.CMN_CN, name: 'Mandarin Chinese'},
    {code: LanguageEnum.CS_CZ, name: 'Czech (Czech Republic)'},
    {code: LanguageEnum.DA_DK, name: 'Danish (Denmark)'},
    {code: LanguageEnum.DE_DE, name: 'German (Germany)'},
    {code: LanguageEnum.EL_GR, name: 'Greek (Greece)'},
    {code: LanguageEnum.EN_AU, name: 'English (Australia)'},
    {code: LanguageEnum.EN_GB, name: 'English (UK)'},
    {code: LanguageEnum.EN_IN, name: 'English (India)'},
    {code: LanguageEnum.EN_US, name: 'English (United States)'},
    {code: LanguageEnum.ES_ES, name: 'Spanish (Spain)'},
    {code: LanguageEnum.ES_US, name: 'Spanish (US)'},
    {code: LanguageEnum.FI_FI, name: 'Finnish (Finland)'},
    {code: LanguageEnum.FR_CA, name: 'French (Canada)'},
    {code: LanguageEnum.FR_FR, name: 'French (France)'},
    {code: LanguageEnum.GU_IN, name: 'Gujarati (India)'},
    {code: LanguageEnum.HE_IL, name: 'Hebrew (Israel)'},
    {code: LanguageEnum.HI_IN, name: 'Hindi (India)'},
    {code: LanguageEnum.HU_HU, name: 'Hungarian (Hungary)'},
    {code: LanguageEnum.ID_ID, name: 'Indonesian (Indonesia)'},
    {code: LanguageEnum.IT_IT, name: 'Italian (Italy)'},
    {code: LanguageEnum.JA_JP, name: 'Japanese (Japan)'},
    {code: LanguageEnum.KN_IN, name: 'Kannada (India)'},
    {code: LanguageEnum.KO_KR, name: 'Korean (South Korea)'},
    {code: LanguageEnum.LT_LT, name: 'Lithuanian (Lithuania)'},
    {code: LanguageEnum.LV_LV, name: 'Latvian (Latvia)'},
    {code: LanguageEnum.ML_IN, name: 'Malayalam (India)'},
    {code: LanguageEnum.MR_IN, name: 'Marathi (India)'},
    {code: LanguageEnum.NB_NO, name: 'Norwegian (Norway)'},
    {code: LanguageEnum.NL_BE, name: 'Dutch (Belgium)'},
    {code: LanguageEnum.NL_NL, name: 'Dutch (Netherlands)'},
    {code: LanguageEnum.PL_PL, name: 'Polish (Poland)'},
    {code: LanguageEnum.PT_BR, name: 'Portuguese (Brazil)'},
    {code: LanguageEnum.RO_RO, name: 'Romanian (Romania)'},
    {code: LanguageEnum.RU_RU, name: 'Russian (Russia)'},
    {code: LanguageEnum.SK_SK, name: 'Slovak (Slovakia)'},
    {code: LanguageEnum.SR_RS, name: 'Serbian (Serbia)'},
    {code: LanguageEnum.SV_SE, name: 'Swedish (Sweden)'},
    {code: LanguageEnum.TA_IN, name: 'Tamil (India)'},
    {code: LanguageEnum.TE_IN, name: 'Telugu (India)'},
    {code: LanguageEnum.TH_TH, name: 'Thai (Thailand)'},
    {code: LanguageEnum.TR_TR, name: 'Turkish (Turkey)'},
    {code: LanguageEnum.UK_UA, name: 'Ukrainian (Ukraine)'},
    {code: LanguageEnum.VI_VN, name: 'Vietnamese (Vietnam)'},
  ];

  // Map Enums to Voice Options
  voices: VoiceOption[] = [
    {id: VoiceEnum.ACHERNAR, name: 'Achernar (Female)', type: 'preset'},
    {id: VoiceEnum.ACHIRD, name: 'Achird (Male)', type: 'preset'},
    {id: VoiceEnum.ALGENIB, name: 'Algenib (Male)', type: 'preset'},
    {id: VoiceEnum.ALGIEBA, name: 'Algieba (Male)', type: 'preset'},
    {id: VoiceEnum.ALNILAM, name: 'Alnilam (Male)', type: 'preset'},
    {id: VoiceEnum.AOEDE, name: 'Aoede (Female)', type: 'preset'},
    {id: VoiceEnum.AUTONOE, name: 'Autonoe (Female)', type: 'preset'},
    {id: VoiceEnum.CALLIRRHOE, name: 'Callirrhoe (Female)', type: 'preset'},
    {id: VoiceEnum.CHARON, name: 'Charon (Male)', type: 'preset'},
    {id: VoiceEnum.DESPINA, name: 'Despina (Female)', type: 'preset'},
    {id: VoiceEnum.ENCELADUS, name: 'Enceladus (Male)', type: 'preset'},
    {id: VoiceEnum.ERINOME, name: 'Erinome (Female)', type: 'preset'},
    {id: VoiceEnum.FENRIR, name: 'Fenrir (Male)', type: 'preset'},
    {id: VoiceEnum.GACRUX, name: 'Gacrux (Female)', type: 'preset'},
    {id: VoiceEnum.IAPETUS, name: 'Iapetus (Male)', type: 'preset'},
    {id: VoiceEnum.KORE, name: 'Kore (Female)', type: 'preset'},
    {id: VoiceEnum.LAOMEDEIA, name: 'Laomedeia (Female)', type: 'preset'},
    {id: VoiceEnum.LEDA, name: 'Leda (Female)', type: 'preset'},
    {id: VoiceEnum.ORUS, name: 'Orus (Male)', type: 'preset'},
    {id: VoiceEnum.PUCK, name: 'Puck (Male)', type: 'preset'},
    {id: VoiceEnum.PULCHERRIMA, name: 'Pulcherrima (Female)', type: 'preset'},
    {id: VoiceEnum.RASALGETHI, name: 'Rasalgethi (Male)', type: 'preset'},
    {id: VoiceEnum.SADACHBIA, name: 'Sadachbia (Male)', type: 'preset'},
    {id: VoiceEnum.SADALTAGER, name: 'Sadaltager (Male)', type: 'preset'},
    {id: VoiceEnum.SCHEDAR, name: 'Schedar (Male)', type: 'preset'},
    {id: VoiceEnum.SULAFAT, name: 'Sulafat (Female)', type: 'preset'},
    {id: VoiceEnum.UMBRIEL, name: 'Umbriel (Male)', type: 'preset'},
    {id: VoiceEnum.VINDEMIATRIX, name: 'Vindemiatrix (Female)', type: 'preset'},
    {id: VoiceEnum.ZEPHYR, name: 'Zephyr (Female)', type: 'preset'},
    {id: VoiceEnum.ZUBENELGENUBI, name: 'Zubenelgenubi (Male)', type: 'preset'},
  ];
  private path = '../../assets/images';

  constructor(
    private searchService: SearchService,
    private audioStateService: AudioStateService,
    private snackBar: MatSnackBar,
    private workspaceStateService: WorkspaceStateService,
    private dialog: MatDialog,
    private sanitizer: DomSanitizer,
    public matIconRegistry: MatIconRegistry,
    @Inject(GalleryService)
    private galleryService: GalleryService,
  ) {
    this.activeAudioJob$ = this.searchService.activeAudioJob$;

    this.matIconRegistry.addSvgIcon(
      'white-gemini-spark-icon',
      this.setPath(`${this.path}/white-gemini-spark-icon.svg`),
    );
  }

  ngOnInit() {
    this.restoreState();
  }

  saveState() {
    this.audioStateService.updateState({
      model: this.selectedModel,
      prompt: this.prompt,
      negativePrompt: this.negativePrompt,
      seed: this.seed,
      sampleCount: this.sampleCount,
      selectedLanguage: this.selectedLanguage,
      selectedVoice: this.selectedVoice,
      // LYRIA_3_PRO_UPGRADE_V1
      durationSeconds: this.durationSeconds,
      lyrics: this.lyrics,
      instrumental: this.instrumental,
    });
  }

  private restoreState() {
    const state = this.audioStateService.getState();
    this.selectedModel = state.model as UiModelType;
    this.prompt = state.prompt;
    this.negativePrompt = state.negativePrompt;
    this.seed = state.seed;
    this.sampleCount = state.sampleCount;
    this.selectedLanguage = state.selectedLanguage as LanguageEnum;
    this.selectedVoice = state.selectedVoice as VoiceEnum;
    // LYRIA_3_PRO_UPGRADE_V1 (reference images intentionally NOT restored --
    // asset selections don't persist across sessions, same as other
    // ephemeral media selections elsewhere in the app)
    this.durationSeconds = state.durationSeconds;
    this.lyrics = state.lyrics || '';
    this.instrumental = state.instrumental || false;
  }

  // LYRIA_REF_IMAGE_FIX_V1: the shared image-selector dialog can return TWO
  // structurally different shapes -- a flat SourceAssetResponseDto (for
  // directly-uploaded images) or a nested MediaItemSelection (for images
  // picked from the generation gallery, e.g. {mediaItem: {...}, selectedIndex}).
  // Both are normalized here into a single display-friendly shape so the
  // template can render either kind's thumbnail correctly, and each is
  // tagged with its source kind so generate() can route it to the correct
  // backend field (reference_image_asset_ids vs reference_media_items).
  openReferenceImageSelector(): void {
    const dialogRef = this.dialog.open(ImageSelectorComponent, {
      width: '90vw',
      height: '80vh',
      maxWidth: '90vw',
      data: {
        mimeType: 'image/*',
        showFooter: true,
        multiSelect: true,
        maxSelection: 10 - this.referenceImageAssets.length,
      },
      panelClass: 'image-selector-dialog',
    });

    dialogRef
      .afterClosed()
      .subscribe(
        (
          result:
            | (MediaItemSelection | SourceAssetResponseDto)[]
            | MediaItemSelection
            | SourceAssetResponseDto
            | undefined,
        ) => {
          if (!result) return;
          // LYRIA_REF_IMAGE_MULTISHAPE_FIX_V1: the shared image-selector dialog does NOT
          // consistently return an array even when multiSelect is true --
          // direct file uploads/crops always close with a single bare
          // object (see uploadAsset/cropperDialogRef subscribers in
          // ImageSelectorComponent), which previously crashed here with
          // "t.map is not a function". Normalize to an array first.
          const resultArray = Array.isArray(result) ? result : [result];
          if (resultArray.length === 0) return;
          const normalized: ReferenceImageRef[] = resultArray
            .map(item => this.normalizeReferenceSelection(item))
            .filter((r): r is ReferenceImageRef => r !== null);
          this.referenceImageAssets = [
            ...this.referenceImageAssets,
            ...normalized,
          ].slice(0, 10);
        },
      );
  }

  // LYRIA_REF_IMAGE_FIX_V1: normalizes either selector result shape into a
  // common { kind, id, mediaIndex?, thumbnailUrl } shape used for display
  // and for building the correct backend request fields.
  private normalizeReferenceSelection(
    item: MediaItemSelection | SourceAssetResponseDto,
  ): ReferenceImageRef | null {
    if ('mediaItem' in item) {
      // Gallery selection: nested shape, arrays for URLs.
      const mediaItem = item.mediaItem as unknown as {
        id: number;
        presignedThumbnailUrls?: string[];
        presignedUrls?: string[];
      };
      const thumbnailUrl =
        mediaItem.presignedThumbnailUrls?.[item.selectedIndex] ||
        mediaItem.presignedUrls?.[item.selectedIndex] ||
        mediaItem.presignedThumbnailUrls?.[0] ||
        mediaItem.presignedUrls?.[0] ||
        '';
      if (!mediaItem.id || !thumbnailUrl) return null;
      return {
        kind: 'media_item',
        id: mediaItem.id,
        mediaIndex: item.selectedIndex,
        thumbnailUrl,
      };
    }
    // Directly-uploaded source asset: flat shape, singular URL fields.
    const asset = item as SourceAssetResponseDto;
    const thumbnailUrl = asset.presignedThumbnailUrl || asset.presignedUrl;
    if (!asset.id || !thumbnailUrl) return null;
    return {
      kind: 'source_asset',
      id: asset.id,
      thumbnailUrl,
    };
  }

  removeReferenceImage(index: number): void {
    this.referenceImageAssets = this.referenceImageAssets.filter(
      (_, i) => i !== index,
    );
  }

  private setPath(url: string): SafeResourceUrl {
    return this.sanitizer.bypassSecurityTrustResourceUrl(url);
  }

  onVoiceSelectionChange(value: string) {
    if (value === 'add-new-voice') {
      this.openAddVoiceDialog();
      this.selectedVoice = '';
    } else {
      this.selectedVoice = value;
    }
    this.saveState();
  }

  openAddVoiceDialog() {
    const dialogRef = this.dialog.open(AddVoiceDialogComponent, {
      width: '500px',
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        const newVoice: VoiceOption = {
          id: `custom-${Date.now()}`, // In real app, this ID comes from backend
          name: result.name,
          type: 'custom',
        };
        this.voices = [newVoice, ...this.voices];
        this.selectedVoice = newVoice.id;
        handleSuccessSnackbar(this.snackBar, 'Voice cloned successfully!');
      }
    });
  }

  generate() {
    this.isLoading = true;
    this.mediaItem = null; // Clear previous result

    const activeWorkspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (!activeWorkspaceId) {
      handleErrorSnackbar(
        this.snackBar,
        {message: 'Please select a workspace first.'},
        'Workspace',
      );
      return;
    }

    // 1. Determine specific backend model based on UI selection
    let backendModel: GenerationModelEnum;

    if (this.selectedModel === 'lyria') {
      backendModel = GenerationModelEnum.LYRIA_002;
    } else if (this.selectedModel === 'lyria-3-pro') {
      // LYRIA_3_PRO_UPGRADE_V1
      backendModel = GenerationModelEnum.LYRIA_3_PRO;
    } else if (this.selectedModel === 'lyria-3-clip') {
      // LYRIA_3_CLIP_UPGRADE_V1
      backendModel = GenerationModelEnum.LYRIA_3_CLIP;
    } else if (this.selectedModel === 'chirp') {
      backendModel = GenerationModelEnum.CHIRP_3;
    } else {
      // GEMINI_3_1_TTS_UPGRADE_V1: use whichever Gemini TTS model the user picked.
      backendModel = this.selectedGeminiTtsModel;
    }

    const isLyria3Pro = this.selectedModel === 'lyria-3-pro'; // LYRIA_3_PRO_UPGRADE_V1
    const isLyria3Clip = this.selectedModel === 'lyria-3-clip'; // LYRIA_3_CLIP_UPGRADE_V1
    const isLyria3 = isLyria3Pro || isLyria3Clip;
    const isAnyLyria = this.selectedModel === 'lyria' || isLyria3;

    // 2. Construct the generic DTO
    const request: CreateAudioDto = {
      model: backendModel,
      prompt: this.prompt,
      workspaceId: activeWorkspaceId,
      // Optional fields (backend ignores them if not relevant to the specific model)
      // Lyria 3 Pro does not support negative_prompt (backend rejects it).
      negativePrompt:
        this.selectedModel === 'lyria' ? this.negativePrompt : undefined,
      seed: this.selectedModel === 'lyria' ? this.seed : undefined,
      sampleCount: this.sampleCount,
      languageCode:
        !isAnyLyria ? (this.selectedLanguage as LanguageEnum) : undefined,
      voiceName: !isAnyLyria ? (this.selectedVoice as VoiceEnum) : undefined,
      // Lyria 3 Pro Specific (LYRIA_3_PRO_UPGRADE_V1)
      // LYRIA_3_CLIP_UPGRADE_V1: duration is Pro-only (Clip always ~30s per
      // Google's docs), but lyrics/instrumental/reference images are
      // supported by both Lyria 3 variants.
      durationSeconds: isLyria3Pro ? this.durationSeconds : undefined,
      lyrics:
        isLyria3 && !this.instrumental ? this.lyrics || undefined : undefined,
      instrumental: isLyria3 ? this.instrumental : undefined,
      // LYRIA_REF_IMAGE_FIX_V1: split combined reference-image list by source
      // kind into the two backend fields it actually expects.
      referenceImageAssetIds: isLyria3
        ? this.referenceImageAssets
            .filter(r => r.kind === 'source_asset')
            .map(r => r.id)
        : undefined,
      referenceMediaItems: isLyria3
        ? this.referenceImageAssets
            .filter(r => r.kind === 'media_item')
            .map(r => ({
              mediaItemId: r.id,
              mediaIndex: r.mediaIndex ?? 0,
              role: 'music_reference',
            }))
        : undefined,
    };

    this.saveState();
    this.audioUrl = null;

    this.searchService.startAudioGeneration(request).subscribe({
      error: (error: any) => {
        handleErrorSnackbar(this.snackBar, error, 'Generation');
        console.error('Generation failed:', error);
      },
    });
  }

  // --- Player Logic ---
  closeErrorOverlay() {
    this.showErrorOverlay = false;
    this.searchService.clearActiveAudioJob();
  }

  togglePlay() {
    const audio = this.audioPlayerRef.nativeElement;
    if (audio.paused) {
      void audio.play();
      this.isPlaying = true;
    } else {
      audio.pause();
      this.isPlaying = false;
    }
  }

  onTimeUpdate() {
    const audio = this.audioPlayerRef.nativeElement;
    if (audio.duration) {
      this.progressValue = (audio.currentTime / audio.duration) * 100;
      this.currentTime = this.formatTime(audio.currentTime);
    }
  }

  seek(value: number) {
    const audio = this.audioPlayerRef.nativeElement;
    if (audio.duration) {
      audio.currentTime = (value / 100) * audio.duration;
    }
  }

  onAudioLoaded() {
    const audio = this.audioPlayerRef.nativeElement;
    this.isPlaying = false;
    this.duration = this.formatTime(audio.duration);
  }

  onAudioEnded() {
    this.isPlaying = false;
    this.progressValue = 0;
    this.currentTime = '0:00';
  }

  private formatTime(seconds: number): string {
    if (isNaN(seconds)) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
  }

  deleteGeneratedMedia() {
    if (!this.mediaItem?.id) return;

    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId === null) return;

    const confirmDelete = confirm(
      'Are you sure you want to delete this generation result?',
    );
    if (!confirmDelete) return;

    this.galleryService
      .bulkDelete([{id: this.mediaItem.id, type: 'media_item'}], workspaceId)
      .subscribe({
        next: () => {
          handleSuccessSnackbar(this.snackBar, 'Audio deleted successfully');
          this.mediaItem = null;
          this.searchService.clearActiveAudioJob();
        },
        error: err => {
          handleErrorSnackbar(this.snackBar, err, 'Delete result');
        },
      });
  }
}
