// item_assets.js — item icon cache by type_id / url
const ItemAssets = (function () {
    const PLACEHOLDER = '/static/items/sprites/placeholder.png';
    const imageCache = Object.create(null);
    const failed = Object.create(null);

    function isImageReady(img) {
        return !!(img && img.complete && img.naturalWidth);
    }

    function loadInto(url) {
        if (!url) {
            return loadInto(PLACEHOLDER);
        }
        if (imageCache[url]) {
            return imageCache[url];
        }
        if (failed[url]) {
            return url === PLACEHOLDER ? null : loadInto(PLACEHOLDER);
        }
        const img = new Image();
        img.onload = function () {};
        img.onerror = function () {
            failed[url] = true;
            if (url !== PLACEHOLDER) {
                console.warn('ItemAssets: failed to load', url);
            }
        };
        img.src = url;
        imageCache[url] = img;
        return img;
    }

    function ensureType(typeId, imageUrl) {
        const url = imageUrl || (typeId ? '/static/items/sprites/' + typeId + '.png' : PLACEHOLDER);
        return loadInto(url);
    }

    function getUrl(typeId, imageUrl) {
        const url = imageUrl || (typeId ? '/static/items/sprites/' + typeId + '.png' : null);
        if (!url || failed[url]) {
            return PLACEHOLDER;
        }
        ensureType(typeId, url);
        return url;
    }

    function getPlaceholder() {
        return PLACEHOLDER;
    }

    return {
        ensureType: ensureType,
        getUrl: getUrl,
        getPlaceholder: getPlaceholder,
        isImageReady: isImageReady,
    };
})();
