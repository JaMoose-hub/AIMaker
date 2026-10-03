import React from "react";
import { Pressable, Text, StyleSheet, View } from "react-native";
export const colors = {
  bg: "#10171d",
  panel: "#1b252d",
  line: "#33434e",
  text: "#edf3f4",
  muted: "#a2b2bc",
  accent: "#68e0cf",
  danger: "#ffba9b",
};
export function Button({
  title,
  onPress,
  disabled = false,
  subtle = false,
}: {
  title: string;
  onPress: () => void;
  disabled?: boolean;
  subtle?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        subtle && styles.subtle,
        disabled && { opacity: 0.4 },
        pressed && { opacity: 0.7 },
      ]}
    >
      <Text
        style={{ color: subtle ? colors.text : "#102a28", fontWeight: "700" }}
      >
        {title}
      </Text>
    </Pressable>
  );
}
export function Notice({ text }: { text: string }) {
  return text ? (
    <View accessibilityLiveRegion="polite" style={styles.notice}>
      <Text selectable style={{ color: colors.danger }}>
        {text}
      </Text>
    </View>
  ) : null;
}
export const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  panel: {
    backgroundColor: colors.panel,
    borderRadius: 16,
    padding: 14,
    gap: 10,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  button: {
    backgroundColor: colors.accent,
    borderRadius: 10,
    paddingVertical: 12,
    paddingHorizontal: 15,
    alignItems: "center",
  },
  subtle: { backgroundColor: colors.line },
  input: {
    backgroundColor: "#101a22",
    borderWidth: 1,
    borderColor: colors.line,
    color: colors.text,
    padding: 12,
    borderRadius: 10,
    minHeight: 46,
  },
  text: { color: colors.text, fontSize: 15, lineHeight: 22 },
  muted: { color: colors.muted, fontSize: 13, lineHeight: 19 },
  title: { color: colors.text, fontSize: 23, fontWeight: "700" },
  notice: { padding: 12, borderRadius: 10, backgroundColor: "#382c29" },
  header: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    gap: 10,
    borderBottomWidth: 1,
    borderColor: colors.line,
  },
});
