export function isPetPreference(value) {
  const text = value.replace(/\s+/g, "");
  if (!/寵物|毛孩|毛小孩|貓|狗|犬|烏龜|陸龜|水龜|兔|鼠|鳥|鸚鵡|魚|蛇|蜥蜴|守宮|刺蝟|蜜袋鼯|爬蟲/.test(text)) return false;
  return !/不養|不飼養|沒有|無寵|不需要|無需|不可|不能|不允許|禁止|不得|謝絕|禁養|禁寵/.test(text);
}

export function setPetPreference(preferences, checked) {
  if (!checked) return preferences.filter((value) => !isPetPreference(value));
  // A species-specific requirement already enables the toggle. Keep it intact.
  return preferences.some(isPetPreference) ? preferences : [...preferences, "可養寵物"];
}
