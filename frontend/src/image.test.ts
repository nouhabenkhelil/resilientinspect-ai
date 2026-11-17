import { MAX_FILE_BYTES, validateFile, validateImage } from './image';

describe('validation des fichiers', () => {
  it.each(['piece.png', 'piece.jpg', 'piece.JPEG'])('accepte %s', (name) => {
    expect(() => validateFile(new File(['image'], name))).not.toThrow();
  });
  it('refuse les extensions et types MIME non pris en charge', () => {
    expect(() => validateFile(new File(['gif'], 'piece.gif'))).toThrow('Format invalide');
    expect(() => validateFile(new File(['svg'], 'piece.png', { type: 'image/svg+xml' }))).toThrow(
      'Type de fichier invalide',
    );
  });
  it('refuse les fichiers vides et ceux dépassant 10 Mio', () => {
    expect(() => validateFile(new File([], 'piece.png'))).toThrow('vide');
    expect(() => validateFile(new File([new Uint8Array(MAX_FILE_BYTES + 1)], 'piece.png'))).toThrow(
      '10 Mio',
    );
    expect(() =>
      validateFile(new File([new Uint8Array(MAX_FILE_BYTES)], 'piece.png')),
    ).not.toThrow();
  });
  it.each([
    [173, 89, true],
    [5000, 4000, true],
    [5001, 4000, false],
    [0, 0, false],
  ])('vérifie les dimensions %i × %i', async (width, height, valid) => {
    vi.stubGlobal(
      'Image',
      class {
        naturalWidth = width;
        naturalHeight = height;
        onload?: () => void;
        set src(_value: string) {
          this.onload?.();
        }
      },
    );
    if (valid) expect(await validateImage('blob:test')).toEqual({ width, height });
    else await expect(validateImage('blob:test')).rejects.toThrow();
  });
  it('signale un décodage local impossible', async () => {
    vi.stubGlobal(
      'Image',
      class {
        onerror?: () => void;
        set src(_value: string) {
          this.onerror?.();
        }
      },
    );
    await expect(validateImage('blob:test')).rejects.toThrow('illisible ou corrompue');
  });
});
