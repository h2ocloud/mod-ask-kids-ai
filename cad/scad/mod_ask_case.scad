// =====================================================================
//  MOD-ASK-20261115-R2  兒童 AI 問答機外殼（R2：實際購買零件＋到貨前先印的容差設計；黑底座／白上殼）
//  板子：Espressif ESP32-S3-DevKitC-1-N16R8（44 腳 2×22）＋INMP441 麥克風＋MAX98357A 功放
//        ＋50 mm 4Ω 3W 喇叭＋0.96" SSD1315 OLED（I2C）＋12×12 觸控開關（按住說話）
//  單位 mm。座標（組裝座標＝給 Onshape 的 STL 座標）：
//    X＝寬（0 置中，+X＝從正面看的右邊）、Y＝深（Y=0＝正面最前下緣，+Y 往後）、Z＝高（Z=0＝桌面側底緣）
//  外觀：白色殼身（上蓋＋三面牆＋U 形額框）＋深色前面板（臉：OLED 視窗、麥克風「鼻孔」、微笑）
//        ＋頂部黃色大圓鈕（Ø40）＋右側喇叭格柵、左側通風「耳朵」＋背面 USB-C 開口。
//  零件：01 base 底座｜02 shell 殼身｜03 front_panel 前面板｜04 button_cap 大圓鈕
//        05 button_clip 卡圈｜06 switch_carrier 開關座（含彈性舌片）｜07 speaker_box 喇叭後腔｜08 speaker_ring 壓環
//  列印：PLA、Cura Low 0.28、全部免支撐（各件列印姿態見 part="print_*" 與 PRINT.md）。
//  OpenSCAD 2026.10.29 snapshot，--backend Manifold。
//  參數可信度標記：【官】原廠圖面/datasheet【文】第三方量測/賣家資料【估】常見值，到貨要量（REPORT.md §5）
// =====================================================================

include <mod_ask_ref.scad>   // 參考零件（只供預覽／干涉檢查，不進列印 STL）

/* [輸出選擇] */
part = "assembly";
// 開發板版型：devkitc1＝Espressif 官方版型（PCB 25.40×62.74，排距 22.86）；yd_s3＝VCC-GND YD-ESP32-S3 雙 USB-C 相容板（27.94×57.15，排距 25.40）
esp_variant = "devkitc1"; // [devkitc1, yd_s3]
// USB 型式（決定背面開口高度）：typec＝brief 所述 USB-C；micro＝官方 v1.1 文件所述 Micro-USB
usb_type = "micro"; // [micro, typec]  只影響參考件與檢查；背面開口一律同時容得下 Micro 與 USB-C 插頭模具殼（R2）
explode = 1.0;      // 爆炸圖倍率

/* [FDM（沿用 th-case 已驗證值）] */
fdm_gap   = 0.30;   // 一般配合間隙（每側）
lh        = 0.28;   // 層高（Cura Low）；只用於 dims 與量化說明

/* [外形（牆厚皆為 0.8 的倍數）] */
W = 116;            // 寬（ESP 69 長板縱放＋右側喇叭模組 32.4＋牆）
D = 92;             // 深（ESP 總長 69.2＋USB 間隙＋前面板斜面）
H = 68;             // 殼身高（不含按鈕凸出 7、腳墊）
Rc = 12;            // 垂直外圓角（平面）≥4
Rt = 6;             // 頂緣外圓角（列印時貼床，45° 截角版）
Rb = 1.2;           // 底緣 45° 倒角
face_tilt = 20;     // 前面板後仰角（自垂直）；小孩坐著從桌面上方約 35–45° 俯視，20° 讓螢幕較正對視線，且 20° 懸空可免支撐
wall  = 2.4;        // 側牆/背牆/前額框
top_t = 2.4;        // 頂板
floor_t = 2.4;      // 底座底板

/* [前面板] */
t_p = 2.4;          // 面板厚
bezel_flat = 3.0;   // 額框兩側平面寬（不含圓角）
ov_top = 2.6;       // 面板上緣藏在額框後的重疊量（沿面板方向）
rib_c = 2.5;        // 頂部擋肋與面板重疊量（面板要先下移 rib_c+0.3 再上推入槽）
open_r = 3.0;       // 臉部開口上方圓角

/* [按鈕（大圓鈕＋導管＋卡圈＋開關座）] */
x_b = 0;  y_b = 56; // 按鈕中心（頂面中央偏後，前緣在斜面之後）
cap_d   = 40;       // 鈕徑（brief ≥35）
cap_gap = 0.7;      // 鈕與殼孔徑向間隙（brief 0.5–0.8）
cap_h   = 7;        // 凸出頂面高度
cap_r   = 4;        // 鈕頂緣圓角（列印時貼床，45° 截角版）
skirt_in = 2.0;     // 裙邊伸入孔內深度
skirt_t  = 2.4;
cap_top_t = 2.4;
btn_travel = 0.9;   // 硬止點行程（鈕下中心面→導管頂）；0.28 層高實得 0.84 或 1.12（REPORT §4）
pin_d   = 6.0;      // 鈕柱（導桿）徑
pin_clr = 0.25;     // 導管徑向間隙
tube_ro = 7.0;      // 導管外半徑
tube_len = 25;      // 導管長（頂面→導管底）；導引長 25/Ø6≈4，偏心按壓不卡（摩擦 0.3 時需偏心 >41 mm 才卡）
cup_h0  = 3.5;      // 鈕孔直壁深度，以下為 45° 漏斗（免支撐）
cone_t  = 1.6;      // 漏斗法向厚
groove_z0 = 2.0;    // 導管外環槽（開關座卡勾用）：距導管底
groove_w  = 1.6;
groove_d  = 1.0;
pin_core  = 4.0;    // 卡圈槽芯徑
pin_gr_w  = 2.6;    // 卡圈槽寬
clip_t    = 2.2;    // 卡圈厚（0.28 量化 2.24）
clip_od   = 10.0;
clip_mouth = 3.8;   // 卡圈開口（< 槽芯 4.0，輕扣）
clip_gap0 = 0.5;    // 靜止時卡圈頂到導管底（另加槽內游隙 0.4）

/* [12×12 觸控開關（CUI TS13-1212-73 類）] */
sw_body = [12, 12, 3.5];   // 本體【官：12×12×7.3 總高；本體高 3.5 為估】
sw_h    = 7.3;             // 含按柱總高【官】
sw_act_d = 3.5;            // 按柱徑【估】
sw_leg_px = 5.0;           // 腳距（短向）【文：5.0–5.08】
sw_leg_py = 12.5;          // 腳距（長向）【文：12.5–12.7】
sw_travel = 0.25;          // 開關行程【估：12×12 常見 0.25±0.1】
sw_force  = 2.5;           // 作動力 N【估：160–260 gf】
shim_t = 0.56;             // R2：開關墊片厚（0.28 層高兩層）
shim_n_nom = 2;            // R2：設計值：標準開關（7.3）墊 2 片；開關每高 0.56 少一片、每矮 0.56 多一片（0–4 片涵蓋 6.2–8.4）
shim_n = shim_n_nom;       // 實際使用片數（參考件／檢查用）
sw_h_nom = 7.3;            // 開關座依 7.3＋2 片設計（sw_h 只給參考件用，量到實物後改 shim_n）

/* [開關座彈性舌片] */
tg_w = 12;  tg_t = 1.6;  tg_a = 17;   // 舌片寬/厚/開關中心到根部（k≈3EI/a³≈7.5 N/mm，E 取 3000；觸發約 0.58；硬止點 0.9 時根部應力≈15 MPa）
slit_w = 1.0;                          // 切縫（沿用 1.0；末端 R0.5）
car_wall = 1.6;                        // 開關座側壁（兼卡勾臂厚）
arm_len  = 12;                         // 卡勾臂長（勾入 0.5 時根部應變≈0.8%）
barb_d   = 0.8;                        // 卡勾內凸

/* [喇叭（50 mm 4Ω 3W；到貨後第 1 優先量）] */
sp_d = 50;          // 外徑【估：Ø50；R2 座圈容許 Ø49–51】
sp_h = 18;          // 總高（框前緣→磁鐵背）【估：18；R2 後腔容許 15–21】
sp_flange_t = 1.6;  // 外緣框厚【估】
sp_basket_d = 46;   // 框後（盆架）最大徑【估；座圈內徑 47 容許到 46.5】
sp_seat_d = 52.0;   // R2：座圈內徑（Ø50 ±1 → 51＋0.5×2）
sp_ledge_id = 47.0; // R2：座圈擋肩內徑（Ø49 喇叭仍有 1.0 寬的支撐）
cb_dep_r2 = 3.0;    // R2：座圈深（框厚 1–2.5＋泡棉，壓環直接坐在筒口）
sp_mag_d = 30;      // 磁鐵徑【估】
box_od = 56;        // 後腔圓筒外徑
box_wall = 2.4;
box_len = 30;       // 後腔總長（背板 2.4＋腔 26＋座 1.6）
y_s = 50;           // 喇叭中心 Y
ring_t = 2.4;       // 壓環厚
ring_id = 44;       // 壓環內徑（只壓外緣 3 mm）
sp_wall_gap = 1.0;  // 壓環到側牆內面（可貼 1–2 mm 泡棉環）
hook_t = 1.2;  hook_w = 5;  hook_barb = 0.6;

/* [格柵／通風（孔 ≤3 mm，小孩手指與小零件塞不進）] */
grille_d  = 2.6;    // 孔徑
grille_p  = 3.8;    // 六角排孔距（肋 1.2 ≥1.0）
grille_R  = 20;     // 格柵圓半徑（Ø40）
vent_w    = 2.4;    // 背面通風直槽寬

/* [ESP32-S3 安裝（排針朝下＋杜邦母頭直插）] */
x_c = -31;          // 板中心 X（左側；天線朝前、USB 朝後牆）
hdr_plastic = 2.5;  // 排針塑膠座【估】
dupont_len  = 14.0; // 杜邦母頭長【估：14–15】
dupont_bend = 6.0;  // 母頭下方彎線空間
pcb_t = 1.6;        // PCB 厚【估：官方圖未標】
pcb_end_gap = 0.3;  // R2：PCB USB 端板邊到背牆內面（拔線時板邊頂住開口中央肋）
usb_rib = 1.0;      // R2：兩個 USB 開口之間的中央肋（擋住 PCB 板邊；YD 版不用）
wedge_gap = 0.5;    // R2：USB 端兩角彈性壓角楔口離 PCB 頂面（沿用 th-case 驗證值）
rail_off = 6.1;     // 兩支撐肋中心距板中心（避開 USB 母座下方插件腳與兩排母頭）
rail_t = 3.2;       // 支撐肋寬（上貼 VHB 雙面泡棉膠）
stop_gap = 0.3;     // 板端前後擋塊間隙
side_gap = 0.4;     // 板側擋柱間隙
plug_c = [12.0, 6.5];      // USB-C 插頭模具殼（brief 值，未取得 USB-IF 原文）
plug_m = [10.6, 8.5];      // Micro-USB 插頭模具殼上限（估）
plug_gap = 0.5;            // 開口每側間隙（brief）
plug = [max(plug_c[0], plug_m[0]), max(plug_c[1], plug_m[1])];   // R2：取兩種插頭的較大者（12.0 × 8.5）

/* [MAX98357A 功放（Adafruit 3006 類）] */
amp_pcb = [19.4, 17.8, 1.6];   // 【官：Adafruit 19.4×17.8×3.0（含零件）；PCB 厚 1.6 估】
amp_x0 = -1.0;  amp_y = 76;    // 板左緣 X、板面 Y（板面朝前、排針朝前、端子朝後）
amp_z0 = 5.4;                  // 板下緣 Z
amp_ref_dx = 0;                // 參考件 X 偏移（容差檢查：大／小板置中）

/* [INMP441 麥克風板] */
mic_pcb = [14, 14, 1.2];   // 【文：多家賣家 14×14；厚 1.2 估】
mic_v = 20;                // 面板座標：麥克風中心（沿面板向上）
mic_hole_d = 1.4;          // 三個收音孔（偏離軸心 3.2，筆直戳入只會碰到錐壁、碰不到麥克風）
mic_hole_r = 3.2;          // R2：2.3→3.2（管孔放大到 Ø4，容許麥克風孔偏 ±1.5）
mic_bore_d = 4.0;          // R2：短管孔（Ø2.5→4.0）
mic_tol = 1.2;             // R2：麥克風板四周游隙（板寬 13–15.4 都放得下）
mic_ref_pcb = mic_pcb;     // 參考件尺寸（容差檢查時用 -D 改大改小，外殼不跟著變）
mic_tube_len = 2.0;        // 短管（面板背→板面，另夾 1.0 泡棉環壓到約 0.6）
foam_t = 0.6;

/* [OLED 0.96" 128×64（模組倒裝：排針朝下，韌體旋轉 180°）] */
oled_pcb = [27.3, 27.8, 1.2];   // 【估：brief 典型值；賣家 26–28 不等】
oled_hole = [11.65, 11.8];      // 孔中心半距【文：買家量測孔距 23.31×23.62】
oled_hole_d = 2.0;              // 【文】
oled_glass = [26.7, 19.26, 1.45];  // 【官：DM-OLED096-624 面板 datasheet】
oled_glass_e = 5.0;             // 玻璃排針側邊緣距 PCB 排針側邊【估】
oled_aa = [21.744, 10.864];     // 可視區【官】
oled_aa_e = 1.9;                // 可視區距玻璃排針側邊【估】
oled_tape = 0.2;
oled_vc = 47.6;                 // 面板座標：OLED PCB 中心
win_m = 1.2;                    // 視窗比可視區每側大（模組位置偏 ±1.2 仍看得到整個可視區）
oled_tol = 1.1;                 // R2：玻璃座四周游隙（玻璃 26.7×19.26、模組偏 ±1 都放得下；台階仍 ≥0.28）
oled_pin_d = 1.5;               // R2：選配定位銷（細、短；孔位不合就用美工刀切掉）
oled_post_u = 18.5;  oled_post_dv = 6.0;   // R2：OLED 壓條螺絲柱（u ±18.5、v＝oled_vc+6）
oled_ref_shift = [0, 0];        // 參考件偏移（容差檢查：模組偏 ±1 仍裝得進）
mic_post_u = 12.5;   mic_post_dv = 1.0;    // R2：麥克風壓條螺絲柱
post_hole = 2.5;                // M3×6 自攻（壓條 2.4 厚＋咬入 3.6，不會穿到臉）
bar_t = 2.4;

/* [螺絲（M3×10 自攻，殼柱孔 Ø2.5）] */
boss_r = 3.5;  boss_h = 8;  boss_hole = 2.5;  boss_hole_dep = 12;
pad_h  = 4.0;           // 底座螺絲墊高（螺頭下留 2.6）
screw_clear = 3.4;  head_d = 6.4;  head_dep = 2.8;
foot_d = 10.6;  foot_dep = 1.0;   // Ø10 圓形防滑腳墊（蓋住螺頭）
lip_h = 4.0;  lip_t = 1.6;        // 底座定位唇

/* [一盤排版] */
bed_x = 220;  bed_y = 220;  bed_back_keep = 20;  plate_gap = 10;
plate_cy = 100;    // 盤面外框中心 Y（可印區 0–200 的中心）

$fa = 4;  $fs = 0.35;
eps = 0.01;  big = 400;

// =====================================================================
//  開發板 lookup 表（板座標→殼座標：板旋轉 180°，USB 端在 +Y 背牆）
// =====================================================================
ESP_TABLE = [
  ["devkitc1", [  // Espressif ESP32-S3-DevKitC-1 v1.1 官方尺寸圖/DXF（DXF_ESP32-S3-DevKitC-1_V1.1_20220429）
    ["pcb_w", 25.40], ["pcb_l", 62.74], ["row", 22.86],
    ["ant_over", 6.5],            // 模組天線凸出 PCB 端（DXF 圖量測，估 ±0.3）
    ["mod_w", 18.0], ["mod_l", 25.5], ["mod_h", 3.1],   // WROOM-1 18×25.5×3.1【官】
    ["pin_end", 8.00],            // 第 22 腳中心距 USB 端板邊【官：8.00 mm】
    ["usb_dx", [6.7, -6.7]],      // [UART, USB] 母座中心距板中心（殼座標 X；DXF J2/J4 中心 6.0/19.4）【官】
    ["usb_over", 0.8]             // 母座凸出板邊（DXF 圖量測）【估】
  ]],
  ["yd_s3", [     // VCC-GND YD-ESP32-S3（Mischianti 公制尺寸 PDF）
    ["pcb_w", 27.94], ["pcb_l", 57.15], ["row", 25.40],
    ["ant_over", 6.24],           // 63.39 − 57.15【文】
    ["mod_w", 18.0], ["mod_l", 25.5], ["mod_h", 3.1],
    ["pin_end", 1.91],            // 【文】
    ["usb_dx", [5.9, -5.9]],      // 由尺寸圖比例量測【估】
    ["usb_over", 0.0]             // 母座在板內【估】
  ]]
];
function etab(k) = let(r = [for (e = ESP_TABLE) if (e[0] == esp_variant) e[1]][0]) [for (p = r) if (p[0] == k) p[1]][0];
pcb_w = etab("pcb_w");  pcb_l = etab("pcb_l");  row = etab("row");
ant_over = etab("ant_over");  mod_w = etab("mod_w");  mod_l = etab("mod_l");  mod_h = etab("mod_h");
pin_end = etab("pin_end");  usb_dx = etab("usb_dx");  usb_over = etab("usb_over");
pin1_off = pcb_l - pin_end - 21*2.54;      // 第 1 腳（天線端）中心距天線端板邊
usb_rec = usb_type == "typec" ? [8.94, 7.35, 3.26] : [7.5, 5.0, 2.8];  // 母座寬/深/高【估：常見型號】
plug_ref = usb_type == "typec" ? plug_c : plug_m;   // 檢查用的插頭

// =====================================================================
//  衍生尺寸
// =====================================================================
a = face_tilt;
function v_at(z, t) = (z - Rb - t*sin(a))/cos(a);     // 面板座標 v（沿面向上）
function zf(v, t) = Rb + v*cos(a) + t*sin(a);
function yf(v, t) = v*sin(a) - t*cos(a);
function dpl(y, z) = -y*cos(a) + (z - Rb)*sin(a);     // 到外前斜面的有號距離（<0 在內）
z_T = H;                                    // 頂面
y_ot = (Rc - Rt) + ((H - Rt - Rb)*sin(a) + Rt)/cos(a);   // 前上角圓角中心 Y
Rt_in = Rt - top_t;
z_fi = H - Rt + Rt_in*sin(a);               // 內前斜面平坦段上緣（面板前面上緣須低於此）
u_o = W/2 - Rc - bezel_flat;                // 臉部開口半寬
u_p = W/2 - Rc - fdm_gap;                   // 面板半寬（內前斜面平坦段 46 − 0.3）
z_pb = floor_t + fdm_gap;                   // 面板下緣（水平切）
z_pt = z_fi - 0.4;                          // 面板前面上緣
v_t  = v_at(z_pt, -wall);
v_ot = v_t - ov_top;                        // 開口上緣
t_pf = -wall - 0.05;  t_pb = t_pf - t_p;     // 面板前/背面（面板座標 t，外為正；前面離額框內面 0.05）
t_rib = t_pb - fdm_gap;                     // 頂擋肋/底座唇的前面

// 按鈕
r_h  = cap_d/2 + cap_gap;
z0c  = z_T - cup_h0;                        // 漏斗起點
cone_h = cone_t*sqrt(2);
zb   = z_T - tube_len;                      // 導管底
r_ti = pin_d/2 + pin_clr;
z_tip = zb - clip_gap0 - 0.4 - clip_t - 1.4;   // 鈕柱尖（靜止）＝開關按柱頂
z_seat = z_tip - sw_h_nom - shim_n_nom*shim_t;   // 舌片頂（R2：開關墊在墊片上；固定設計值）
car_z0 = z_seat - tg_t;                     // 開關座底
car_top = zb + groove_z0 + groove_w + 1.0;  // 開關座頂
car_in_x = tube_ro + fdm_gap;               // 開關座內壁半寬（X）
car_out_x = car_in_x + car_wall;
car_in_y = 8.6;  car_out_y = car_in_y + 1.6;
tail_y = tg_a + 2.4;                        // 舌片根部後的框
z_cone_bot = z0c - (r_h + cone_h - tube_ro);   // 漏斗外面與導管交會

// 喇叭
z_s  = floor_t + 1.0 + box_od/2;            // 喇叭中心 Z（筒底離底板 1.0）
x_wall_in = W/2 - wall;
x_rf = x_wall_in - sp_wall_gap;             // 壓環外面
x_bf = x_rf - ring_t;                       // 後腔筒口（R2：壓環直接坐在筒口，喇叭框＋泡棉在 3.0 深的座圈內被壓住）
x_bb = x_bf - box_len;                      // 後腔背板外面
cb_dep = cb_dep_r2;
x_ledge = x_bf - cb_dep;                    // 喇叭框背面
win_x0 = x_bf - 10.2;  win_x1 = x_bf - 8.2; // 後腔卡窗（軸向）

// ESP
z_pcb = floor_t + dupont_bend + dupont_len + hdr_plastic;  // PCB 底面
y_pe = D - wall - pcb_end_gap;              // PCB USB 端（R2：與母座凸出量無關）
y_pf = y_pe - pcb_l;                        // PCB 天線端
y_ant = y_pf - ant_over;                    // 天線尖
z_usb = z_pcb + pcb_t + 1.5;                // USB 母座中心高（Micro 約 +1.4、USB-C 約 +1.63，取 1.5；開口高 9.5 涵蓋兩者）
rib_w = esp_variant == "yd_s3" ? 0 : usb_rib;
usb_open = [abs(usb_dx[0] - usb_dx[1]) + plug[0] + 2*plug_gap, plug[1] + 2*plug_gap];   // 外框（含中央肋）
function pin_y(n) = y_pf + pin1_off + (n - 1)*2.54;       // 第 n 腳（自天線端）
esp_wedge = esp_variant == "devkitc1";      // 官方版 USB 端兩角上方沒有元件（DXF：板邊 1.9 內、距板端 6.3 內），可加彈性壓角

// 螺絲柱位置（[x, y, 伸向牆的方向]）
boss_pos = [[-49.5, 17.5, [-1, 0]], [49.5, 17.5, [1, 0]], [-50.0, 84.0, [-1, 1]], [50.0, 84.0, [1, 1]]];
z_boss0 = floor_t + pad_h;                  // 殼柱底面＝底座螺絲墊頂
function foot_c(p) = [p[0], p[1]] - p[2]/norm(p[2])*2.0;          // 腳墊中心往內偏 2.0（Ø10 腳墊仍蓋住 Ø6.4 沉孔與 Ø5.6 螺頭，且不超出底座外形）

// 麥克風距喇叭格柵（直線）
mic_world = [0, yf(mic_v, t_pf), zf(mic_v, t_pf)];
grille_c  = [W/2, y_s, z_s];
mic_spk_dist = norm(mic_world - grille_c) - grille_R;

// ---------------- 基本幾何斷言 ----------------
assert(u_p > u_o + 2.0, "面板兩側要藏在額框後 ≥2");
assert(v_t - v_ot >= 2.5, "面板上緣重疊 ≥2.5");
assert(y_ant - yf(v_at(z_pcb + pcb_t, t_pb), t_pb) > 2.5, "天線尖離面板背 >2.5");
assert(x_bb > x_b + (r_h + cone_h - (z0c - (z_s + box_od/2))) + 0.5, "喇叭後腔頂（z_s+28）不碰按鈕漏斗外面");
assert(car_top < z_cone_bot + (car_in_x - tube_ro) - 0.4, "開關座頂不碰漏斗");
assert(mic_spk_dist >= 40, "麥克風孔距喇叭格柵 ≥40");
assert(x_c - pcb_w/2 - side_gap - 1.6 > -x_wall_in + 6, "ESP 側擋柱不碰左牆");
assert(boss_pos[2][0] + boss_r < x_c - pcb_w/2 - 0.5, "左後螺絲柱不碰 ESP");

// =====================================================================
//  共用小工具
// =====================================================================
module face_frame() multmatrix([[1, 0, 0, 0], [0, sin(a), -cos(a), 0], [0, cos(a), sin(a), Rb], [0, 0, 0, 1]]) children();
module face_frame_inv() multmatrix([[1, 0, 0, 0], [0, sin(a), cos(a), -Rb*cos(a)], [0, -cos(a), sin(a), -Rb*sin(a)], [0, 0, 0, 1]]) children();
// 45° 截角圓盤：平面半徑 R、邊緣圓角 r，頂部（+Z）超過 45° 的圓弧改為 45° 斜面（倒置列印免支撐）
module puck45(R, r) rotate_extrude() hull() {
    translate([R - r, 0]) circle(r);
    translate([0, -r]) square([eps, 2*r]);
    translate([0, r - eps]) square([R - r + r*(sqrt(2) - 1), eps]);
}
module puck0(R, r) rotate_extrude() hull() { translate([R - r, 0]) circle(r); translate([0, -r]) square([eps, 2*r]); }
module hex_holes(R, d, p) for (j = [-12 : 12], i = [-12 : 12]) {
    x = (i + (abs(j) % 2)*0.5)*p;  y = j*p*sqrt(3)/2;
    if (norm([x, y]) <= R - d/2) translate([x, y]) circle(d = d, $fn = 20);
}
module stadium(w, h) hull() for (s = [-1, 1]) translate([s*(w/2 - h/2), 0]) circle(d = h);

// =====================================================================
//  外殼外形與內腔（hull 由角件組成，內腔＝同心縮小）
// =====================================================================
module outer_solid() hull() for (sx = [-1, 1]) {
    translate([sx*(W/2 - Rc), Rc, 0]) cylinder(r1 = Rc - Rb, r2 = Rc, h = Rb);
    translate([sx*(W/2 - Rc), D - Rc, 0]) cylinder(r1 = Rc - Rb, r2 = Rc, h = Rb);
    translate([sx*(W/2 - Rc), y_ot, H - Rt]) puck45(Rc, Rt);
    translate([sx*(W/2 - Rc), D - Rc, H - Rt]) puck45(Rc, Rt);
}
// g：再往內縮 g（底座外形用 g=fdm_gap）
module inner_cavity(g = 0) {
    rr = Rc - wall - g;
    yfb = rr + ((-1 - Rb)*sin(a) + wall + g)/cos(a);
    hull() for (sx = [-1, 1]) {
        translate([sx*(W/2 - Rc), yfb, -1]) cylinder(r = rr, h = eps);
        translate([sx*(W/2 - Rc), D - Rc, -1]) cylinder(r = rr, h = eps);
        translate([sx*(W/2 - Rc), y_ot, H - Rt]) puck0(rr, Rt_in - g);
        translate([sx*(W/2 - Rc), D - Rc, H - Rt]) puck0(rr, Rt_in - g);
    }
}

// =====================================================================
//  02 殼身 shell
// =====================================================================
module cup_tube_solid() translate([x_b, y_b, 0]) {
    // 直壁＋45° 漏斗（法向厚 cone_t）
    rotate_extrude() polygon([
        [r_h - 0.02, z_T - top_t + eps], [r_h - 0.02, z0c], [tube_ro - eps, z0c - (r_h - 0.02 - tube_ro)],
        [tube_ro - eps, z_cone_bot], [r_h + cone_h, z0c], [r_h + cone_h, z_T - top_t + eps]]);
    // 導管（頂面齊平；列印時從床面長起）
    translate([0, 0, zb]) cylinder(r = tube_ro, h = z_T - zb);
}
module cup_tube_cuts() translate([x_b, y_b, 0]) {
    difference() { translate([0, 0, z0c]) cylinder(r = r_h, h = z_T - z0c + 1); translate([0, 0, z0c - 1]) cylinder(r = tube_ro - 0.02, h = 50); }
    translate([0, 0, zb - 1]) cylinder(r = r_ti, h = z_T - zb + 2);                       // 導管孔
    translate([0, 0, zb + groove_z0]) difference() { cylinder(r = tube_ro + 1, h = groove_w); translate([0, 0, -1]) cylinder(r = tube_ro - groove_d, h = groove_w + 2); }
    translate([0, 0, zb - eps]) difference() { cylinder(r = tube_ro + 1, h = 0.6); cylinder(r1 = tube_ro - 0.6, r2 = tube_ro, h = 0.6); }  // 導管底外緣 0.6 導角
}
module boss(p) {
    c = [p[0], p[1]];  dv = p[2];
    translate([c[0], c[1], z_boss0]) cylinder(r = boss_r, h = boss_h);
    // 45° 托角：往牆斜上（倒置列印時托住柱子）
    hull() {
        translate([c[0], c[1], z_boss0 + boss_h - eps]) cylinder(r = boss_r, h = eps);
        translate([c[0] + dv[0]*12, c[1] + dv[1]*12, z_boss0 + boss_h + 12*norm(dv)]) cylinder(r = boss_r, h = eps);
    }
    // 連到牆的肋（1.6）
    hull() {
        translate([c[0], c[1], z_boss0]) cylinder(r = 0.8, h = boss_h);
        translate([c[0] + dv[0]*12, c[1] + dv[1]*12, z_boss0]) cylinder(r = 0.8, h = boss_h + 12*norm(dv));
    }
}
module shell_inner_features() {
    cup_tube_solid();
    for (p = boss_pos) boss(p);
    // 面板頂部擋肋（面板上緣滑入肋與額框之間）
    face_frame() translate([-30, v_t - rib_c, t_rib - 1.6]) cube([60, 30, 1.6]);
    // 喇叭後腔壓肋
    for (x = [x_bb + 7, x_bf - 13]) difference() {
        translate([x - 0.8, y_s - 12, z_s]) cube([1.6, 24, H]);
        translate([x - 1, y_s, z_s]) rotate([0, 90, 0]) cylinder(r = box_od/2 + 0.3, h = 3);
    }
}
module face_opening() face_frame() translate([0, 0, -wall - 1]) linear_extrude(wall + 2)
    hull() {
        translate([-u_o, -30]) square([2*u_o, 1]);
        for (s = [-1, 1]) translate([s*(u_o - open_r), v_ot - open_r]) circle(r = open_r);
    }
module usb_opening() translate([x_c, D - wall - 1, z_usb]) rotate([-90, 0, 0]) linear_extrude(wall + 2) {
    // 圓角 1.0 矩形，左右各一（中央留 rib_w 的肋擋住 PCB 板邊；肋寬 0 時合成一個）
    xo = usb_open[0]/2;
    for (s = [-1, 1]) translate([s*(rib_w/2 + (xo - rib_w/2)/2), 0]) offset(r = 1.0) square([xo - rib_w/2 - 2, usb_open[1] - 2], center = true);
}
module side_grille(sx) {
    translate([sx*(W/2 - wall - 1), y_s, z_s]) rotate([0, sx*90, 0]) linear_extrude(wall + 2) hex_holes(grille_R, grille_d, grille_p);
    // 「耳朵」外圈裝飾槽（深 0.8、寬 1.6；牆剩 1.6）
    translate([sx*(W/2 - 0.8), y_s, z_s]) rotate([0, sx*90, 0]) linear_extrude(2) difference() { circle(r = grille_R + 3.2); circle(r = grille_R + 1.6); }
}
module back_vents() for (i = [-2 : 2]) translate([i*(vent_w + 3.2), D - wall - 1, 50]) hull() for (z = [0, 10]) translate([0, 0, z]) rotate([-90, 0, 0]) cylinder(d = vent_w, h = wall + 2, $fn = 16);
module boss_holes() for (p = boss_pos) translate([p[0], p[1], z_boss0 - 1]) cylinder(d = boss_hole, h = boss_hole_dep + 1, $fn = 24);

module shell() difference() {
    union() {
        difference() { outer_solid(); inner_cavity(0); }
        intersection() { outer_solid(); shell_inner_features(); }
    }
    face_opening();
    cup_tube_cuts();
    side_grille(1);                 // 右：喇叭格柵
    side_grille(-1);                // 左：ESP 艙通風「耳朵」
    usb_opening();
    back_vents();
    boss_holes();
}

// =====================================================================
//  01 底座 base
// =====================================================================
module base_slab(z0, z1) translate([-big/2, -big/2, z0]) cube([big, big, z1 - z0]);
module front_strip() intersection() {
    outer_solid();
    face_frame() translate([-(u_o - fdm_gap), -30, -wall - 2]) cube([2*(u_o - fdm_gap), 60, wall + 2]);
    base_slab(0, floor_t);
}
module perimeter_lip() difference() {
    intersection() { inner_cavity(fdm_gap); base_slab(floor_t - eps, floor_t + lip_h); }
    inner_cavity(fdm_gap + lip_t);
    translate([-big/2, -big/2, 0]) cube([big, big/2 + 26, 50]);            // 前段不做（面板／前柱）
    translate([x_bb - 2, y_s - 32, 0]) cube([60, 64, 50]);                 // 喇叭模組
    for (p = boss_pos) translate([p[0], p[1], 0]) cylinder(r = boss_r + 6, h = 50);
}
module panel_lip() intersection() {
    face_frame() translate([-40, -20, t_rib - lip_t]) cube([80, 60, lip_t]);
    base_slab(floor_t - eps, floor_t + 6);
}
module screw_pads() intersection() {
    inner_cavity(fdm_gap);
    for (p = boss_pos) translate([p[0], p[1], floor_t - eps]) cylinder(r = 5, h = pad_h + eps);
}
module wedge_post(s, xc, yw0, yw1, zp) {
    xi = xc + s*(pcb_w/2 + side_gap);  xo = xi + s*1.6;
    zh = zp + pcb_t + wedge_gap - side_gap;          // 楔口 45° 斜面在柱內面的高度
    translate([min(xi, xo), yw0, floor_t - eps]) cube([1.6, yw1 - yw0, zh + side_gap + 2.2 - floor_t]);
    translate([0, yw1, 0]) rotate([90, 0, 0]) linear_extrude(yw1 - yw0)
        polygon(s > 0 ? [[xi + 0.01, zh], [xi - side_gap - 1.2, zh + side_gap + 1.2], [xi - side_gap - 1.2, zh + side_gap + 2.2], [xi + 0.01, zh + side_gap + 2.2]]
                      : [[xi - 0.01, zh], [xi + side_gap + 1.2, zh + side_gap + 1.2], [xi + side_gap + 1.2, zh + side_gap + 2.2], [xi - 0.01, zh + side_gap + 2.2]]);
}
module esp_cradle() {
    ya = y_pf - stop_gap - 1.0;                         // 前擋塊前面
    yb = y_pe - 0.5;                                    // 支撐肋後端
    for (s = [-1, 1]) {
        xr = x_c + s*rail_off;
        // 支撐肋（PCB 底面中央，上貼 VHB 雙面泡棉膠）
        translate([xr - rail_t/2, ya, floor_t - eps]) cube([rail_t, yb - ya, z_pcb - floor_t + eps]);
        // 天線端前擋（高 1.2 < PCB 1.6，不碰模組下緣）
        translate([xr - rail_t/2, ya, z_pcb - eps]) cube([rail_t, 1.0, 1.2 + eps]);
        // 側擋柱：在第 12 腳（J1-12＝GPIO8 未用、J3-12＝GPIO36 為 PSRAM 腳）外側，母頭寬度以外
        yt = pin_y(12);
        xi = x_c + s*(pcb_w/2 + side_gap);  xo = xi + s*1.6;
        translate([min(xi, xo), yt - 2, floor_t - eps]) cube([1.6, 4, z_pcb + 1.0 - floor_t + eps]);
        translate([min(xr, xo), yt - 2, floor_t - eps]) cube([abs(xo - xr), 4, 2.4]);
        // R2：USB 端兩角彈性壓角（細柱可彎；45° 楔口壓住 PCB 板角上緣，楔口間隙 wedge_gap）
        if (esp_wedge) {
            wedge_post(s, x_c, y_pe - 5.0, y_pe - 1.5, z_pcb);
            translate([min(xr, xo), y_pe - 5.0, floor_t - eps]) cube([abs(xo - xr), 3.5, 2.4]);
        }
    }
}
module speaker_cradle() {
    for (x = [x_bb + 4, x_bb + 14]) difference() {
        translate([x - 1.2, y_s - 20, floor_t - eps]) cube([2.4, 40, z_s - 14 - floor_t]);
        translate([x - 2, y_s, z_s]) rotate([0, 90, 0]) cylinder(r = box_od/2 + 0.3, h = 4);
    }
    // 背板 X 向擋（避開出線孔）
    translate([x_bb - 0.3 - 1.6, y_s - 8, floor_t - eps]) cube([1.6, 16, z_s - 12 - floor_t]);
}
module amp_holder() {
    // R2：兩根卡槽柱夾住板左右緣；槽寬 2.4（板厚 1.0–2.0）、槽深 3.0，柱距容許板寬 15.6–21.4；
    //     前／後夾片只做在 z>10–12（排針塑膠座與穿出的短腳都在板下緣）
    bc = amp_x0 + 19.4/2;   // 以 Adafruit 19.4 寬為中心設計（實物另以參考件 amp_pcb 檢查容差）
    for (m = [0, 1]) translate([bc, 0, 0]) mirror([m, 0, 0]) translate([-bc, 0, 0]) {
        xe = amp_x0 - 1.0;  y0 = amp_y - 0.2;  y1 = amp_y + 2.2;
        translate([xe - 1.6, y1, 10]) cube([4.6, 1.6, amp_z0 + 12 - 10]);                                // 後夾片（z>10，避開排針穿出板背的短腳）
        translate([xe - 1.6, y0 - 1.6, 12]) cube([4.6, 1.6, amp_z0 + 12 - 12]);                          // 前夾片
        translate([xe - 1.6, y0 - 1.6, floor_t - eps]) cube([1.6, y1 - y0 + 3.2, amp_z0 + 12 - floor_t]); // 外側柱
        translate([xe - 1.6, y0 - 1.6, floor_t - eps]) cube([4.6, y1 - y0 + 3.2, amp_z0 - floor_t + eps]); // 下托
    }
}
module base_cuts() {
    for (p = boss_pos) {
        fc = foot_c(p);
        translate([fc[0], fc[1], -1]) cylinder(d = foot_d, h = foot_dep + 1);
        translate([p[0], p[1], -1]) cylinder(d = head_d, h = foot_dep + head_dep + 1);
        translate([p[0], p[1], -1]) cylinder(d = screw_clear, h = floor_t + pad_h + 2);
    }
    // ESP 下方通風槽
    for (dx = [-10, -2.6, 2.6, 10]) translate([x_c + dx, y_pf + 12, -1]) hull() for (dy = [0, 30]) translate([0, dy, 0]) cylinder(d = 2.0, h = floor_t + 2, $fn = 16);
}
module base() difference() {
    union() {
        intersection() { inner_cavity(fdm_gap); base_slab(0, floor_t); }
        front_strip();
        perimeter_lip();
        panel_lip();
        screw_pads();
        esp_cradle();
        speaker_cradle();
        amp_holder();
    }
    base_cuts();
}

// =====================================================================
//  03 前面板 front_panel（面板座標 u,v,t；t 外為正）
// =====================================================================
oled_win_c = oled_vc - oled_pcb[1]/2 + oled_glass_e + oled_aa_e + oled_aa[1]/2;   // 可視區中心 v（倒裝：排針側在下）
oled_glass_c = oled_vc - oled_pcb[1]/2 + oled_glass_e + oled_glass[1]/2;
t_glass_f = t_pb + 1.2;            // 玻璃前面（玻璃座深 1.2，面板前皮 1.2）
t_oled_pcb_f = t_glass_f - oled_glass[2] - oled_tape;   // OLED PCB 前面
t_mic_f = t_pb - mic_tube_len - foam_t;                 // 麥克風板前面
t_oled_b = t_oled_pcb_f - oled_pcb[2];                  // OLED PCB 背面（標稱）
t_bar_o = t_oled_b - 2.1;                               // R2：OLED 壓條下面（中間夾 3 mm 泡棉）
t_bar_m = t_mic_f - mic_pcb[2] - 2.0;                   // R2：麥克風壓條下面（中間夾 3 mm 泡棉）
module post_at(u, v, t_top, d) translate([u, v, t_top]) difference() {
    cylinder(d = d, h = t_pb - t_top + eps);
    translate([0, 0, -1]) cylinder(d = post_hole, h = min(5.0, t_pb - t_top) + 1, $fn = 20);   // 盲孔，不穿到臉
}
module panel_body() {
    v_b0 = v_at(z_pb, t_pb) - 2;
    difference() {
        union() {
            translate([-u_p, v_b0, t_pb]) cube([2*u_p, v_t - v_b0, t_p]);
            // OLED 選配定位銷（細、短）
            if (oled_pin_d > 0) for (su = [-1, 1], sv = [-1, 1]) translate([su*oled_hole[0], oled_vc + sv*oled_hole[1], t_oled_b - 0.6]) cylinder(d = oled_pin_d, h = t_pb - (t_oled_b - 0.6) + eps, $fn = 16);
            // OLED 壓條螺絲柱、麥克風壓條螺絲柱
            for (su = [-1, 1]) post_at(su*oled_post_u, oled_vc + oled_post_dv, t_bar_o, 7);
            for (su = [-1, 1]) post_at(su*mic_post_u, mic_v + mic_post_dv, t_bar_m, 6);
            // 麥克風短管
            translate([0, mic_v, t_pb - mic_tube_len]) cylinder(d = 10, h = mic_tube_len + eps);
            mic_guides();
        }
        // OLED 視窗（前面 45° 斜角）＋玻璃座（四周 oled_tol 游隙）
        translate([0, oled_win_c, 0]) hull() {
            translate([0, 0, t_glass_f - eps]) linear_extrude(eps) offset(r = 0.5) square([oled_aa[0] + 2*win_m - 1, oled_aa[1] + 2*win_m - 1], center = true);
            translate([0, 0, t_pf]) linear_extrude(eps + 0.01) offset(r = 0.5 + (t_pf - t_glass_f)) square([oled_aa[0] + 2*win_m - 1, oled_aa[1] + 2*win_m - 1], center = true);
        }
        translate([-(oled_glass[0] + 2*oled_tol)/2, oled_glass_c - (oled_glass[1] + 2*oled_tol)/2, t_pb - 1]) cube([oled_glass[0] + 2*oled_tol, oled_glass[1] + 2*oled_tol, 1 + 1.2]);
        // OLED 排針短腳＋焊點讓位槽（深 1.0；R2 加大 ±1）
        translate([-(4*2.54/2 + 1.9), oled_vc - oled_pcb[1]/2 + 1.3 - 2.6, t_pb - 1]) cube([4*2.54 + 3.8, 5.2, 1 + 1.0]);
        // 麥克風：三個偏心收音孔→前室 Ø9→45° 錐→Ø4 管孔
        for (k = [0 : 2]) translate([mic_hole_r*cos(90 + k*120), mic_v + mic_hole_r*sin(90 + k*120), t_pf - 1.2 - eps]) cylinder(d = mic_hole_d, h = 2, $fn = 16);
        translate([0, mic_v, t_pf - 1.2 - 0.6]) cylinder(r = 4.5, h = 0.6 + eps);
        translate([0, mic_v, t_pf - 1.2 - 0.6 - (4.5 - mic_bore_d/2)]) cylinder(r1 = mic_bore_d/2, r2 = 4.5, h = 4.5 - mic_bore_d/2 + eps);
        translate([0, mic_v, t_pb - mic_tube_len - 1]) cylinder(d = mic_bore_d, h = 3.0, $fn = 24);
        // 微笑（前面刻 0.8）
        translate([0, mic_v + 1, t_pf - 0.8]) linear_extrude(1) smile2d();
    }
}
module smile2d() {
    r = 15;  w = 2.0;
    intersection() {
        difference() { circle(r = r + w/2); circle(r = r - w/2); }
        polygon([[0, 0], [r*2*cos(212), r*2*sin(212)], [0, -r*2], [r*2*cos(328), r*2*sin(328)]]);
    }
    for (ang = [212, 328]) translate([r*cos(ang), r*sin(ang)]) circle(d = w);
}
module mic_guides() {
    // R2：麥克風板放在兩側擋牆之間（游隙 mic_tol），坐在下擋上，由壓條＋泡棉壓向短管上的泡棉環
    hw = mic_pcb[0]/2 + mic_tol;  vstop = mic_v - mic_pcb[1]/2 - 0.5;  vt = mic_v + mic_pcb[1]/2 + 1.5;
    tback = t_mic_f - mic_pcb[2] - 1.0;
    for (s = [-1, 1]) translate([s > 0 ? hw : -hw - 1.6, vstop - 1.6, tback]) cube([1.6, vt - vstop + 1.6, t_pb - tback + eps]);
    translate([-hw - 1.6, vstop - 1.6, tback]) cube([2*hw + 3.2, 1.6, t_pb - tback + eps]);   // 下擋（只擋板緣；排針在板後）
}
// 壓條（面板座標，組裝位置）：中間兩個 M3 長孔（±0.8 可調）
module bar_shape(len, w) difference() {
    hull() for (s = [-1, 1]) translate([s*(len/2 - w/2), 0]) circle(d = w);
    for (s = [-1, 1]) hull() for (d = [-0.8, 0.8]) translate([s*(len/2 - w/2) + d, 0]) circle(d = 3.4, $fn = 20);
}
module oled_bar() face_frame() translate([0, oled_vc + oled_post_dv, t_bar_o - bar_t]) linear_extrude(bar_t) bar_shape(2*oled_post_u + 8, 8);
module mic_bar() face_frame() translate([0, mic_v + mic_post_dv, t_bar_m - bar_t]) linear_extrude(bar_t) bar_shape(2*mic_post_u + 7, 7);
// 開關墊片組（4 片，以 0.8 寬細橋相連，用手折開；每片 12×12×0.56，開腳孔）
module shim2d() difference() {
    offset(r = 1) square([10, 10], center = true);
    for (sx = [-1, 1], sy = [-1, 1]) translate([sx*sw_leg_px/2, sy*sw_leg_py/2]) square([2.2, 2.0], center = true);
}
module switch_shim_card() linear_extrude(shim_t) {
    for (i = [0 : 3]) translate([0, i*14]) shim2d();
    for (i = [0 : 2]) translate([-0.4, i*14 + 6]) square([0.8, 2]);
}
module front_panel() intersection() {
    face_frame() panel_body();
    translate([-big/2, -big/2, z_pb]) cube(big);
}

// =====================================================================
//  04 大圓鈕 button_cap（組裝座標，靜止位置）
// =====================================================================
module button_cap() translate([x_b, y_b, 0]) {
    difference() {
        union() {
            // 頂（45° 截角圓邊）＋裙邊
            intersection() {
                translate([0, 0, z_T + cap_h - cap_r]) puck45(cap_d/2, cap_r);
                translate([0, 0, z_T - skirt_in]) cylinder(d = cap_d + 1, h = cap_h + skirt_in);
            }
            translate([0, 0, z_T - skirt_in]) cylinder(d = cap_d, h = cap_h + skirt_in - cap_r);
        }
        // 內部挖空（中央留止點凸台 r=8.5，凸台下面＝硬止點面）
        difference() {
            translate([0, 0, z_T - skirt_in - 1]) cylinder(d = cap_d - 2*skirt_t, h = skirt_in + 1 + cap_h - cap_top_t);
            translate([0, 0, z_T + btn_travel]) cylinder(r = 8.5, h = cap_h);
        }
        // 頂面刻「?」1.0
        translate([0, 0, z_T + cap_h - 1.0]) linear_extrude(1.5) text("?", size = 20, font = "Liberation Sans:style=Bold", halign = "center", valign = "center");
    }
    // 鈕柱（導桿）＋卡圈槽＋尖端導角
    difference() {
        translate([0, 0, z_tip]) cylinder(d = pin_d, h = z_T + btn_travel - z_tip + eps);
        translate([0, 0, zb - clip_gap0 - 0.4 - clip_t - 0.05]) difference() { cylinder(d = pin_d + 1, h = pin_gr_w); translate([0, 0, -1]) cylinder(d = pin_core, h = pin_gr_w + 2); }
        translate([0, 0, z_tip - eps]) difference() { cylinder(d = pin_d + 1, h = 0.5); cylinder(d1 = pin_d - 1, d2 = pin_d, h = 0.5); }
    }
}

// =====================================================================
//  05 卡圈 button_clip（組裝座標：靜止時落在槽下肩）
// =====================================================================
module button_clip() translate([x_b, y_b, zb - clip_gap0 - 0.4 - clip_t]) linear_extrude(clip_t) difference() {
    circle(d = clip_od);
    circle(d = pin_core + 0.1);
    translate([0, -clip_mouth/2]) square([clip_od, clip_mouth]);
    // 開口導角
    translate([clip_od/2, 0]) rotate(45) square(2.2, center = true);
}

// =====================================================================
//  06 開關座 switch_carrier（卡在導管外環槽；開關坐在彈性舌片上）
// =====================================================================
module carrier_floor2d() difference() {
    translate([-car_out_x, -car_out_y]) square([2*car_out_x, car_out_y + tail_y]);
    // U 形切縫（兩側＋前端），末端 R0.5
    for (s = [-1, 1]) hull() {
        translate([s*(tg_w/2 + slit_w/2), -car_in_y + slit_w/2]) circle(d = slit_w, $fn = 16);
        translate([s*(tg_w/2 + slit_w/2), tg_a]) circle(d = slit_w, $fn = 16);
    }
    translate([-(tg_w/2 + slit_w), -car_in_y]) square([tg_w + 2*slit_w, slit_w]);
    // 開關腳孔（4 支，腳沿 Y）
    for (sx = [-1, 1], sy = [-1, 1]) translate([sx*sw_leg_px/2, sy*sw_leg_py/2]) square([2.2, 2.0], center = true);   // R2：放大，焊點＋線可通過
}
module switch_carrier() translate([x_b, y_b, car_z0]) {
    h = car_top - car_z0;
    linear_extrude(tg_t) carrier_floor2d();
    difference() {
        union() {
            for (s = [-1, 1]) translate([s > 0 ? car_in_x : -car_out_x + 0.01, -car_out_y + 0.01, 0.5]) cube([car_wall - 0.01, 2*car_out_y - 0.02, h - 0.5]);   // 側壁（外面內縮 0.01，避免與底板共面）
            translate([-car_out_x + 0.01, -car_out_y + 0.01, 0.5]) cube([2*car_out_x - 0.02, 1.6, h - 0.5]);                       // 前壁
            translate([-car_out_x + 0.01, car_in_y, tg_t + 1.6]) cube([2*car_out_x - 0.02, 1.6 - 0.01, h - tg_t - 1.6]);         // 後橋（跨在舌片上方 1.6）
        }
        // 卡勾臂切縫（每側兩條，末端 R0.5）
        for (s = [-1, 1], sy = [-1, 1]) translate([s*(car_in_x + car_wall/2), sy*3.5, h - arm_len]) hull() {
            translate([0, 0, 0.5]) rotate([0, 90, 0]) cylinder(d = 1.0, h = car_wall + 1, center = true, $fn = 16);
            translate([0, 0, arm_len + 1]) cube([car_wall + 1, 1.0, eps], center = true);
        }
    }
    // 卡勾（內凸 barb_d；下面水平承力，上面 45° 導入）
    for (s = [-1, 1]) translate([0, 0, zb + groove_z0 - car_z0]) mirror([s < 0 ? 1 : 0, 0, 0])
        translate([car_in_x, -3 + 0.0, 0]) rotate([90, 0, 0]) mirror([0, 0, 1]) linear_extrude(6)
            polygon([[eps, 0], [-barb_d, 0], [-barb_d, 0.6], [eps, 0.6 + barb_d]]);
}

// =====================================================================
//  07 喇叭後腔 speaker_box、08 壓環 speaker_ring（軸向 +X）
// =====================================================================
ring_boss = 0.6;    // R2：壓環內圈往座圈內凸 0.6（框厚 1.0–2.4 都壓得到；中間夾 1–2 mm 泡棉）
module speaker_box() translate([x_bb, y_s, z_s]) rotate([0, 90, 0]) difference() {
    R = box_od/2;  rs = sp_seat_d/2;  rl = sp_ledge_id/2;  rc = R - box_wall;  L = box_len;
    rotate_extrude() polygon([[0, 0], [R, 0], [R, L - 0.8], [R - 0.8, L], [rs, L], [rs, L - cb_dep], [rl, L - cb_dep],
                              [rc, L - cb_dep - (rc - rl)], [rc, box_wall], [0, box_wall]]);
    // 卡窗（4 個，45° 方位）
    for (k = [0 : 3]) rotate([0, 0, 45 + 90*k]) translate([R - box_wall - 1, -(hook_w + 1)/2, L - (x_bf - win_x0)]) cube([box_wall + 2, hook_w + 1, win_x1 - win_x0]);
    // 出線孔 Ø3（背板，往後下；裝好後以熱熔膠封住）
    translate([15*cos(45), 15*sin(45), -1]) cylinder(d = 3, h = box_wall + 2, $fn = 20);
}
module speaker_ring() translate([x_bf + 0.05, y_s, z_s]) rotate([0, 90, 0]) {
    difference() {
        union() {
            cylinder(d = box_od, h = ring_t);
            translate([0, 0, -ring_boss]) cylinder(d1 = sp_seat_d - 1.2 - 2*ring_boss, d2 = sp_seat_d - 1.2, h = ring_boss + eps);   // 內凸壓肩（45° 導角）
        }
        translate([0, 0, -2]) cylinder(d = ring_id, h = ring_t + 4);
    }
    for (k = [0 : 3]) rotate([0, 0, 45 + 90*k]) {
        // 卡勾臂（沿 −X＝這裡的 −Z）
        translate([box_od/2 + 0.3, -hook_w/2, -(x_bf - win_x0)]) cube([hook_t, hook_w, (x_bf - win_x0) + ring_t]);
        // 勾頭（承力面朝 +X，背面 45° 導入）
        translate([box_od/2 + 0.3, hook_w/2, -(x_bf - win_x1) - 0.1]) rotate([90, 0, 0]) linear_extrude(hook_w)
            polygon([[eps, 0], [-hook_barb, 0], [-hook_barb, -(win_x1 - win_x0) + 0.4 + hook_barb], [eps, -(win_x1 - win_x0) + 0.4]]);
        // 臂與環的連接角
        translate([box_od/2 - 1.0, -hook_w/2, 0]) cube([1.3 + hook_t, hook_w, ring_t]);
    }
}

// =====================================================================
//  著色、組裝、爆炸、剖面、盤面
// =====================================================================
C_SHELL = "#f2f0eb";  C_BASE = "#2b2d31";  C_PANEL = "#f7f6f2";  C_CAP = "#1e1f23";   // R2：只有黑／白 PLA
C_INNER = "#26282c";  C_BOX = "#303236";  C_RING = "#2a2c30";
module c_shell() color(C_SHELL) shell();
module c_base() color(C_BASE) base();
module c_panel() color(C_PANEL) front_panel();
module c_cap(dz = 0) color(C_CAP) translate([0, 0, dz]) button_cap();
module c_clip(dz = 0) color(C_INNER) translate([0, 0, dz]) button_clip();
module c_carrier(dz = 0) color(C_INNER) translate([0, 0, dz]) switch_carrier();
module c_box() color(C_BOX) speaker_box();
module c_ring() color(C_RING) speaker_ring();
module c_bars() color(C_INNER) { oled_bar(); mic_bar(); switch_shims_asm(); }
module parts_all(wires = true) { esp_ref(); mic_ref(); amp_ref(); oled_ref(); speaker_ref(); switch_ref(); }

module assembly(cut = false) {
    c_shell(); c_base(); c_panel(); c_cap(); c_clip(); c_carrier(); c_box(); c_ring(); c_bars(); parts_all();
}

// 選印試配片：殼頂按鈕區（Ø54 頂板＋鈕孔＋漏斗＋導管＋環槽），約 1 h；配正式的鈕、卡圈、開關座先試手感
module fit_button_test() intersection() { shell(); translate([x_b, y_b, zb - 1]) cylinder(r = 27, h = H); }
// 列印姿態（各件以 bbox 置中於原點、z=0 貼床）
module switch_shims_asm(n = shim_n) if (n > 0) for (i = [0 : n - 1]) translate([x_b, y_b, z_seat + i*shim_t + 0.01]) linear_extrude(shim_t - 0.02) shim2d();

// ---------------- 選配快速試配片（COUPON 盤，≤30 min） ----------------
// ① 喇叭座圈：後腔筒口那一段（座圈 Ø52、擋肩 Ø47、深 3.0）＋實際壓環可直接試扣（卡窗不在此段）
module coupon_speaker() translate([0, 0, -(box_len - cb_dep - 0.6)]) intersection() {
    print_pose("speaker_box");
    translate([-big/2, -big/2, box_len - cb_dep - 0.6]) cube(big);
}
// ② OLED：視窗＋台階＋玻璃座＋排針讓位槽＋兩個壓條螺絲柱（配實際的 oled_bar 試）
module coupon_oled() translate([0, 0, t_pf]) rotate([180, 0, 0]) intersection() {
    face_frame_inv() front_panel();
    translate([0, 0, -30]) linear_extrude(40) union() {
        translate([-(oled_glass[0]/2 + oled_tol + 2), oled_vc - oled_pcb[1]/2 - 1.5]) square([oled_glass[0] + 2*oled_tol + 4, oled_pcb[1] + 1.0]);
        translate([-(oled_post_u + 4), oled_vc + oled_post_dv - 3.5]) square([2*oled_post_u + 8, 7]);
    }
}
// ③ USB 開口（平放；插 Micro 與 USB-C 線試）
module usb_open2d() { xo = usb_open[0]/2; for (s = [-1, 1]) translate([s*(rib_w/2 + (xo - rib_w/2)/2), 0]) offset(r = 1.0) square([xo - rib_w/2 - 2, usb_open[1] - 2], center = true); }
module coupon_usb() linear_extrude(wall) difference() { offset(r = 2) square([usb_open[0] + 3, usb_open[1] + 3], center = true); usb_open2d(); }
// ④ ESP 板側擋段：短支撐肋（4 mm）＋USB 端兩角彈性壓角＋側距（驗證 PCB 寬／厚、楔口）＋母頭高度量規（22.5＝PCB 底離底板）
module coupon_esp() {
    zp = 1.6 + 4.0;   // 試片的 PCB 底面高度
    translate([-(pcb_w/2 + side_gap + 2.6), 0, 0]) cube([pcb_w + 2*side_gap + 5.2, 12, 1.6]);
    for (s = [-1, 1]) {
        translate([s*rail_off - rail_t/2, 2, 1.6 - eps]) cube([rail_t, 9, 4.0 + eps]);
        translate([0, 0, 1.6 - floor_t]) wedge_post(s, 0, 2.0, 5.5, zp - (1.6 - floor_t));
    }
    // 母頭高度量規（平放）：長 22.5＝實機 PCB 底面離底板的高度；把插好母頭的板子側放在旁邊比對（母頭＋彎線不可超過）
    translate([-4, 12 - eps, 0]) cube([8, dupont_bend + dupont_len + hdr_plastic, 1.2]);
    translate([-4, 12 + dupont_bend, 1.2 - eps]) cube([8, 0.8, 0.6]);   // 刻度：彎線空間 6 處
}

// 列印姿態（各件 z=0 貼床）
module print_pose(name) {
    if (name == "base") base();
    else if (name == "shell") translate([0, 0, H]) rotate([180, 0, 0]) shell();
    else if (name == "front_panel") translate([0, 0, t_pf]) rotate([180, 0, 0]) face_frame_inv() front_panel();
    else if (name == "button_cap") translate([0, 0, z_T + cap_h]) rotate([180, 0, 0]) button_cap();
    else if (name == "button_clip") translate([0, 0, -(zb - clip_gap0 - 0.4 - clip_t)]) button_clip();
    else if (name == "switch_carrier") translate([0, 0, -car_z0]) switch_carrier();
    else if (name == "speaker_box") translate([0, 0, -x_bb]) rotate([0, -90, 0]) speaker_box();
    else if (name == "speaker_ring") translate([0, 0, x_bf + 0.05 + ring_t]) rotate([0, 90, 0]) speaker_ring();
    else if (name == "oled_bar") linear_extrude(bar_t) bar_shape(2*oled_post_u + 8, 8);
    else if (name == "mic_bar") linear_extrude(bar_t) bar_shape(2*mic_post_u + 7, 7);
    else if (name == "switch_shim_card") switch_shim_card();
    else if (name == "fit_button_test") translate([0, 0, H]) rotate([180, 0, 0]) fit_button_test();
    else if (name == "coupon_speaker") coupon_speaker();
    else if (name == "coupon_oled") coupon_oled();
    else if (name == "coupon_usb") coupon_usb();
    else if (name == "coupon_esp") coupon_esp();
}
// 由 build 量得的列印姿態 bbox（xmin,xmax,ymin,ymax）
include <../build/print_bbox.scad>
function bw(bb) = bb[1] - bb[0];
function bh(bb) = bb[3] - bb[2];
// 以「外框左下角」放置；rot=90 時先轉 90°（外框寬高互換）
module place_at(name, x0, y0, bb, rot = 0) {
    if (rot == 0) translate([x0 - bb[0], y0 - bb[2], 0]) print_pose(name);
    else translate([x0 + bb[3], y0 - bb[0], 0]) rotate([0, 0, 90]) print_pose(name);
}
// ASK 專用區（BRIEF_R2_ADD）：件實體 X 6–152、Y 6–194（每件四周留 brim 5 mm＋1）
ZX0 = 6;  ZX1 = 152;  ZY0 = 6;  ZY1 = 194;
G = plate_gap;    // 件距 10（≥8）
BLACK_LAYOUT = [   // [名稱, x0, y0, rot]
  ["base",             ZX0, ZY0, 90],
  ["button_cap",       ZX0 + 89.4 + 8, ZY0, 0],
  ["switch_carrier",   ZX0 + 89.4 + 8, ZY0 + 40 + 8, 0],
  ["switch_shim_card", ZX0 + 89.4 + 8 + 17.8 + 8, ZY0 + 40 + 8, 0],
  ["button_clip",      ZX0 + 89.4 + 8, ZY0 + 40 + 8 + 29.6 + 8, 0],
  ["oled_bar",         ZX0 + 89.4 + 8, 116, 0],
  ["speaker_box",      ZX0, 132, 0],
  ["speaker_ring",     ZX0 + 56 + 8, 132, 0],
  ["mic_bar",          ZX0 + 56 + 8 + 59.4 + 8, 132, 90]
];
WHITE_LAYOUT = [
  ["shell",       ZX0, ZY0, 0],
  ["front_panel", ZX0, ZY0 + 92 + 8, 0]
];
COUPON_LAYOUT = [
  ["coupon_speaker", 20, 20, 0],
  ["coupon_oled",    86, 20, 0],
  ["coupon_usb",     86, 66, 0],
  ["coupon_esp",     20, 86, 0]
];
function bb_of(n) = n == "base" ? BB_base : n == "shell" ? BB_shell : n == "front_panel" ? BB_front_panel : n == "button_cap" ? BB_button_cap
    : n == "button_clip" ? BB_button_clip : n == "switch_carrier" ? BB_switch_carrier : n == "speaker_box" ? BB_speaker_box : n == "speaker_ring" ? BB_speaker_ring
    : n == "oled_bar" ? BB_oled_bar : n == "mic_bar" ? BB_mic_bar : n == "switch_shim_card" ? BB_switch_shim_card
    : n == "coupon_speaker" ? BB_coupon_speaker : n == "coupon_oled" ? BB_coupon_oled : n == "coupon_usb" ? BB_coupon_usb : BB_coupon_esp;
module plate_from(L) for (it = L) place_at(it[0], it[1], it[2], bb_of(it[0]), it[3]);
function col_of(n) = (n == "shell" || n == "front_panel") ? (n == "shell" ? C_SHELL : C_PANEL) : C_BASE;
module plate_view() {
    for (k = [0 : 1]) translate([k*250, 0, 0]) {
        L = k == 0 ? BLACK_LAYOUT : WHITE_LAYOUT;
        for (it = L) color(col_of(it[0])) place_at(it[0], it[1], it[2], bb_of(it[0]), it[3]);
        color("#bfbfbf") translate([0, 0, -1.2]) cube([bed_x, bed_y - bed_back_keep, 1]);
        color("#e07a6a") translate([0, bed_y - bed_back_keep, -1.2]) cube([bed_x, bed_back_keep, 1]);
        color("#9fc5e8") translate([162, 0, -1.1]) cube([58, bed_y - bed_back_keep, 1]);     // WIFI 專用區（別的專案）
        color("#7a7a7a") translate([ZX0, ZY0, -1.15]) difference() { cube([ZX1 - ZX0, ZY1 - ZY0, 1]); translate([0.8, 0.8, -1]) cube([ZX1 - ZX0 - 1.6, ZY1 - ZY0 - 1.6, 3]); }
        color("#222") translate([4, bed_y - bed_back_keep + 6, -0.2]) linear_extrude(0.2) text(k == 0 ? "ASK_BLACK (black PLA)" : "ASK_WHITE (white PLA)", size = 8, font = "Liberation Sans:style=Bold");
        color("#225") translate([164, 90, -0.2]) linear_extrude(0.2) text("WIFI zone", size = 6, font = "Liberation Sans:style=Bold");
    }
}
module coupons_view() for (it = COUPON_LAYOUT) color(C_BASE) place_at(it[0], it[1], it[2], bb_of(it[0]), it[3]);

module exploded() {
    e = explode;
    translate([0, 0, -52*e]) { c_base(); translate([0, 0, 16*e]) { esp_ref(); amp_ref(); } }
    translate([62*e, 0, -30*e]) { c_box(); speaker_ref(); translate([26*e, 0, 0]) c_ring(); }
    translate([0, -78*e, -14*e]) { c_panel(); oled_ref(); mic_ref(); color(C_INNER) face_frame() translate([0, 0, -12*e]) face_frame_inv() { oled_bar(); mic_bar(); } }
    translate([0, 0, 40*e]) c_shell();
    translate([0, 0, 100*e]) c_cap();
    translate([0, 0, 8*e]) { c_carrier(); color(C_INNER) translate([0, 0, 3*e]) switch_shims_asm(); translate([0, 0, 6*e]) switch_ref(); }
    translate([0, 0, 26*e]) c_clip();
}

module cutbox(w) if (w == 0) translate([-big, -big/2, -big/2]) cube(big); else translate([-big/2, y_b, -big/2]) cube(big);
module sect(w) {   // 每件各自上剖面色（剖面＝較深的同色系）
    intersection() { c_shell(); color("#cfcac0") cutbox(w); }
    intersection() { c_base(); color("#55585e") cutbox(w); }
    intersection() { c_panel(); color("#d6d2c8") cutbox(w); }
    intersection() { c_cap(); color("#55585e") cutbox(w); }
    intersection() { union() { c_clip(); c_carrier(); c_bars(); } color("#5a5d63") cutbox(w); }
    intersection() { union() { c_box(); c_ring(); } color("#4c4f55") cutbox(w); }
    intersection() { parts_all(); color("#2d2d2d") cutbox(w); }
}
module section_view() {
    // 上：X=0 縱剖（按鈕軸、麥克風、OLED；看 X<0 半邊，背景可見 ESP）→ 轉 90° 讓剖面朝相機（−Y）
    translate([0, 0, 88]) rotate([0, 0, -90]) translate([0, -D/2, 0]) sect(0);
    // 下：Y=y_b 橫剖（按鈕軸、ESP、功放、喇叭後腔；看 Y>y_b 半邊）
    translate([0, -y_b, 0]) sect(1);
}

if (part == "shell") shell();
else if (part == "base") base();
else if (part == "front_panel") front_panel();
else if (part == "button_cap") button_cap();
else if (part == "button_clip") button_clip();
else if (part == "switch_carrier") switch_carrier();
else if (part == "speaker_box") speaker_box();
else if (part == "speaker_ring") speaker_ring();
else if (starts_with(part, "print_")) print_pose(substr(part, 6));
else if (part == "ASK_BLACK") plate_from(BLACK_LAYOUT);
else if (part == "ASK_WHITE") plate_from(WHITE_LAYOUT);
else if (part == "COUPON") plate_from(COUPON_LAYOUT);
else if (part == "plate_view") plate_view();
else if (part == "coupons_view") coupons_view();
else if (part == "oled_bar") oled_bar();
else if (part == "mic_bar") mic_bar();
else if (part == "switch_shim_1") switch_shims_asm(1);
else if (part == "switch_shim_2") translate([0, 0, shim_t]) switch_shims_asm(1);
else if (part == "assembly") assembly();
else if (part == "exploded") exploded();
else if (part == "section") section_view();
else if (part == "front") assembly();
else if (part == "open") { c_base(); c_panel(); c_clip(); c_carrier(); c_box(); c_ring(); parts_all(); }
else if (part == "open_shell") { c_shell(); c_cap(); c_clip(); c_carrier(); switch_ref(); }
else if (part == "top") assembly();
else if (part == "fit_button_test") fit_button_test();
else if (part == "ref_esp") esp_ref();
else if (part == "ref_mic") mic_ref();
else if (part == "ref_amp") amp_ref();
else if (part == "ref_oled") oled_ref();
else if (part == "ref_speaker") speaker_ref();
else if (part == "ref_switch") switch_ref();
else if (part == "plan") {
    // 給 tools/make_slice_plan.py：盤面配置與關鍵特徵（組裝座標或面板座標）
    echo(str("PLAN ", "{\"H\":", H, ",\"x_b\":", x_b, ",\"y_b\":", y_b, ",\"r_h\":", r_h, ",\"tube_ro\":", tube_ro, ",\"r_ti\":", r_ti,
        ",\"cup_h0\":", cup_h0, ",\"mic_v\":", mic_v, ",\"mic_hole_r\":", mic_hole_r, ",\"oled_win_c\":", oled_win_c,
        ",\"win\":[", oled_aa[0] + 2*win_m, ",", oled_aa[1] + 2*win_m, "],\"tg_w\":", tg_w, ",\"slit_w\":", slit_w, ",\"tg_a\":", tg_a,
        ",\"car_in_y\":", car_in_y, ",\"tg_t\":", tg_t, ",\"clip_od\":", clip_od, ",\"clip_mouth\":", clip_mouth, ",\"clip_t\":", clip_t,
        ",\"ring_id\":", ring_id, ",\"y_s\":", y_s, ",\"z_s\":", z_s, ",\"foot_d\":", foot_d, ",\"foot_dep\":", foot_dep, ",\"head_d\":", head_d,
        ",\"boss\":[", boss_str(boss_pos), "]",
        ",\"black\":[", lay_str(BLACK_LAYOUT), "]",
        ",\"white\":[", lay_str(WHITE_LAYOUT), "]",
        ",\"coupon\":[", lay_str(COUPON_LAYOUT), "]",
        "}"));
    cube(1);
} else if (part == "dims") {
    echo(str("DIMS {\"W\":", W, ",\"D\":", D, ",\"H\":", H, ",\"cap_top\":", z_T + cap_h, ",\"face_tilt\":", face_tilt,
        ",\"z_pcb\":", z_pcb, ",\"y_pe\":", y_pe, ",\"y_pf\":", y_pf, ",\"y_ant\":", y_ant, ",\"z_usb\":", z_usb,
        ",\"usb_open\":[", usb_open[0], ",", usb_open[1], "],\"zb\":", zb, ",\"z_tip\":", z_tip, ",\"z_seat\":", z_seat,
        ",\"car_z0\":", car_z0, ",\"car_top\":", car_top, ",\"z_cone_bot\":", z_cone_bot, ",\"btn_travel\":", btn_travel,
        ",\"x_bb\":", x_bb, ",\"x_bf\":", x_bf, ",\"y_s\":", y_s, ",\"z_s\":", z_s, ",\"mic_spk_dist\":", mic_spk_dist,
        ",\"mic_world\":[", mic_world[0], ",", mic_world[1], ",", mic_world[2], "],\"v_t\":", v_t, ",\"v_ot\":", v_ot,
        ",\"z_pt\":", z_pt, ",\"u_o\":", u_o, ",\"u_p\":", u_p, ",\"oled_win_c\":", oled_win_c, ",\"tg_k\":", 3*3000*(tg_w*pow(tg_t, 3)/12)/pow(tg_a, 3),
        ",\"rib_w\":", rib_w, ",\"shim_t\":", shim_t, ",\"pcb_w\":", pcb_w, ",\"pcb_l\":", pcb_l, ",\"variant\":\"", esp_variant, "\",\"usb_type\":\"", usb_type, "\"}"));
    cube(1);
}
function lay_str(L, i = 0) = i >= len(L) ? "" : str(i ? "," : "", "[\"", L[i][0], "\",", L[i][1], ",", L[i][2], ",", L[i][3], "]", lay_str(L, i + 1));
function boss_str(L, i = 0) = i >= len(L) ? "" : str(i ? "," : "", "[", L[i][0], ",", L[i][1], ",", L[i][2][0], ",", L[i][2][1], "]", boss_str(L, i + 1));
function substr(s, i) = i >= len(s) ? "" : str(s[i], substr(s, i + 1));
function starts_with(s, p) = len(s) >= len(p) && [for (i = [0 : len(p) - 1]) s[i]] == [for (i = [0 : len(p) - 1]) p[i]];
