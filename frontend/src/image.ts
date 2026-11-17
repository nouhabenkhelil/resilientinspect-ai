export const MAX_FILE_BYTES = 10 * 1024 * 1024;
export const MAX_IMAGE_PIXELS = 20_000_000;

export function validateFile(file: File): void {
  if (!/\.(png|jpe?g)$/i.test(file.name))
    throw new Error('Format invalide. Importez une image PNG ou JPEG.');
  if (file.type && !['image/png', 'image/jpeg'].includes(file.type))
    throw new Error('Type de fichier invalide. Une image PNG ou JPEG est requise.');
  if (file.size === 0) throw new Error('Le fichier est vide. Choisissez une autre image.');
  if (file.size > MAX_FILE_BYTES) throw new Error('Le fichier dépasse la limite de 10 Mio.');
}

// L’API garde la validation définitive du format réel, des animations et du contenu.
export function validateImage(url: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      if (image.naturalWidth * image.naturalHeight > MAX_IMAGE_PIXELS) {
        reject(new Error('L’image dépasse la limite de 20 millions de pixels.'));
      } else if (!image.naturalWidth || !image.naturalHeight) {
        reject(new Error('Les dimensions de l’image sont invalides.'));
      } else resolve({ width: image.naturalWidth, height: image.naturalHeight });
    };
    image.onerror = () => reject(new Error('Cette image est illisible ou corrompue.'));
    image.src = url;
  });
}
