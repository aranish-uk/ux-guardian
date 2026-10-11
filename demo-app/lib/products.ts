export const products = [
  { id: "everyday-tote", name: "Everyday tote", price: 28, category: "Carry", icon: "◧", color: "sand", description: "Room for the everyday. A sturdy cotton tote with a little extra space." },
  { id: "ceramic-cup", name: "Ceramic cup", price: 18, category: "Home", icon: "◡", color: "mint", description: "A quieter start to the morning. A simple ceramic cup for your favorite brew." },
  { id: "pocket-notebook", name: "Pocket notebook", price: 12, category: "Desk", icon: "▤", color: "rose", description: "For ideas on the move. Unlined pages in a compact, soft-cover notebook." },
] as const;

export type Product = typeof products[number];
