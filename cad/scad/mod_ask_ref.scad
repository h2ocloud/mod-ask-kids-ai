// =====================================================================
//  mod_ask_ref.scad — 參考零件（只供預覽、干涉檢查與剖面圖；不進列印 STL）
//  ESP32-S3-DevKitC-1（PCB、WROOM-1 模組、USB 母座、按鍵、排針、杜邦母頭）、INMP441、MAX98357A、
//  50 mm 喇叭、0.96" OLED、12×12 觸控開關、USB-C 插頭（檢查用）。
//  本檔不定義參數，全部引用 mod_ask_case.scad 的全域值（include 時才解析）。
//  與殼體接觸的面一律留 0.05 間隙，讓干涉檢查可以直接判 EMPTY。
// =====================================================================

C_PCB_ESP = "#1d1f24";  C_PCB_BLUE = "#1f4fa0";  C_PIN = "#d4af37";  C_HDR = "#151515";
C_METAL = "#c6cad0";  C_DUP = "#1a1a1a";  C_GLASS = "#0d1117";  C_AA = "#10324a";

// ---------------- 杜邦母頭（套在排針長端；dir＝針尖方向單位向量） ----------------
module dupont_at(p, dir, col = C_DUP) {
    // p：排針塑膠座外表面中心
    color(col) translate(p) rotate(dir == [0, 0, -1] ? [180, 0, 0] : dir == [0, -1, 0] ? [90, 0, 0] : dir == [0, 1, 0] ? [-90, 0, 0] : [0, 0, 0])
        translate([-1.3, -1.3, 0]) cube([2.6, 2.6, dupont_len]);
}

// ---------------- ESP32-S3-DevKitC-1 ----------------
// 板座標→殼座標：USB 端在 +Y（y_pe），天線端在 −Y（y_pf），元件面朝上，排針長端朝下
// 使用中的腳（自天線端第 n 腳）：J1（殼 +X 側）、J3（殼 −X 側）
J1_USED = [1, 2, 4, 5, 6, 7, 8, 9, 21, 22];
J3_USED = [1, 6, 7, 17, 21, 22];
module esp_ref(duponts = true) {
    zt = z_pcb + pcb_t + 0.05;          // 參考件比支撐面高 0.05
    zp = z_pcb + 0.05;
    color(C_PCB_ESP) translate([x_c - pcb_w/2, y_pf, zp]) cube([pcb_w, pcb_l, pcb_t]);
    // WROOM-1 模組（含天線凸出）
    color(C_PCB_ESP) translate([x_c - mod_w/2, y_ant, zt]) cube([mod_w, mod_l, 0.8]);
    color(C_METAL) translate([x_c - mod_w/2 + 0.6, y_ant + ant_over + 0.5, zt + 0.8]) cube([mod_w - 1.2, mod_l - ant_over - 1.1, mod_h - 0.8]);
    color("#b08d2b") translate([x_c - mod_w/2 + 1.5, y_ant + 0.8, zt + 0.8]) cube([mod_w - 3, 0.6, 0.05]);   // 天線走線示意
    // 兩個 USB 母座
    for (dx = usb_dx) color(C_METAL) translate([x_c + dx - usb_rec[0]/2, y_pe + usb_over - usb_rec[1], zt]) cube([usb_rec[0], usb_rec[1], usb_rec[2]]);
    // BOOT / RST 按鍵、RGB LED（示意，官方 DXF 位置）
    for (b = [[12.7 - 6.76, 13.8], [12.7 - 17.17, 13.9]]) color("#333") translate([x_c + b[0] - 2, y_pe - b[1] - 1.5, zt]) cube([4, 3, 1.6]);
    // 排針（塑膠座在 PCB 底、針長端朝下；上方短針）
    for (s = [-1, 1]) {
        color(C_HDR) translate([x_c + s*row/2 - 1.27, pin_y(1) - 1.27, zp - hdr_plastic]) cube([2.54, 22*2.54, hdr_plastic]);
        for (n = [1 : 22]) color(C_PIN) translate([x_c + s*row/2 - 0.32, pin_y(n) - 0.32, zp - hdr_plastic - 6]) cube([0.64, 0.64, 6 + hdr_plastic + pcb_t + 1.5]);
    }
    if (duponts) {
        for (n = J1_USED) dupont_at([x_c + row/2, pin_y(n), zp - hdr_plastic - 0.05], [0, 0, -1], n <= 2 || n == 21 ? "#d62728" : n == 22 ? "#202020" : "#e8c21a");
        for (n = J3_USED) dupont_at([x_c - row/2, pin_y(n), zp - hdr_plastic - 0.05], [0, 0, -1], n == 1 || n >= 21 ? "#202020" : "#3a7bd5");
    }
}

// ---------------- INMP441（面板座標；收音孔朝面板、排針朝後） ----------------
module mic_ref() face_frame() translate([0, (mic_ref_pcb[1] - 14)/2 - 0.45, 0]) {   // 板子坐在下擋上（下擋頂＝mic_v−7.5，留 0.05）
    mic_pcb = mic_ref_pcb;   // 容差檢查用
    tf = t_mic_f - 0.05;
    color(C_PCB_BLUE) difference() {
        translate([-mic_pcb[0]/2, mic_v - mic_pcb[1]/2, tf - mic_pcb[2]]) cube(mic_pcb);
        translate([0, mic_v, tf - 5]) cylinder(d = 1.0, h = 10, $fn = 12);
    }
    color("#cfcfcf") translate([-2.4, mic_v - 1.9, tf - mic_pcb[2] - 1.0]) cube([4.7, 3.8, 1.0]);   // INMP441 晶片（底面）
    // 泡棉環（示意）
    color("#3b3b3b") translate([0, mic_v, t_pb - mic_tube_len - foam_t]) difference() { cylinder(d = 10, h = foam_t - 0.05); translate([0, 0, -1]) cylinder(d = mic_bore_d, h = 3); }
    // 6P 排針（下緣，朝後）＋母頭
    for (i = [0 : 5]) {
        color(C_PIN) translate([(i - 2.5)*2.54 - 0.32, mic_v - mic_pcb[1]/2 + 1.3 - 0.32, tf - mic_pcb[2] - 2.5 - 6]) cube([0.64, 0.64, 6 + 2.5 + mic_pcb[2] + 0.5]);
    }
    color(C_HDR) translate([-6*2.54/2, mic_v - mic_pcb[1]/2 + 1.3 - 1.27, tf - mic_pcb[2] - 2.5]) cube([6*2.54, 2.54, 2.5]);
    for (i = [0 : 5]) color(C_DUP) translate([(i - 2.5)*2.54 - 1.25, mic_v - mic_pcb[1]/2 + 1.3 - 1.25, tf - mic_pcb[2] - 2.5 - dupont_len - 0.05]) cube([2.5, 2.5, dupont_len]);
}

// ---------------- MAX98357A（板面在 XZ 平面；排針朝 −Y，端子朝 +Y） ----------------
module amp_ref() translate([amp_ref_dx, 0, 0]) {
    y0 = amp_y + 0.05;  z0 = amp_z0 + 0.05;
    color(C_PCB_BLUE) translate([amp_x0 + 0.05, y0, z0]) cube([amp_pcb[0] - 0.1, amp_pcb[2], amp_pcb[1]]);
    color("#222") translate([amp_x0 + amp_pcb[0]/2 - 1.5, y0 + amp_pcb[2], z0 + 8]) cube([3, 0.8, 3]);                // MAX98357A
    color("#2a9d4a") translate([amp_x0 + amp_pcb[0]/2 - 3.6, y0 + amp_pcb[2], z0 + amp_pcb[1] - 7.5]) cube([7.2, 8.0, 7.5]);   // 3.5 mm 端子台
    color(C_HDR) translate([amp_x0 + amp_pcb[0]/2 - 7*2.54/2, y0 - 2.5, z0 + 1.3 - 1.27]) cube([7*2.54, 2.5, 2.54]);
    for (i = [0 : 6]) {
        color(C_PIN) translate([amp_x0 + amp_pcb[0]/2 + (i - 3)*2.54 - 0.32, y0 - 2.5 - 6, z0 + 1.3 - 0.32]) cube([0.64, 6 + 2.5 + amp_pcb[2] + 0.5, 0.64]);
        color(C_DUP) translate([amp_x0 + amp_pcb[0]/2 + (i - 3)*2.54 - 1.25, y0 - 2.5 - dupont_len - 0.05, z0 + 1.3 - 1.25]) cube([2.5, dupont_len, 2.5]);
    }
}

// ---------------- 0.96" OLED（倒裝：排針側在下；面板座標） ----------------
module oled_ref() face_frame() translate([oled_ref_shift[0], oled_ref_shift[1], 0]) {
    tg = t_glass_f - 0.05;
    tpf = tg - oled_glass[2] - oled_tape;
    pb = oled_vc - oled_pcb[1]/2;      // PCB 下緣（排針側）
    color(C_PCB_BLUE) difference() {
        translate([-oled_pcb[0]/2, pb, tpf - oled_pcb[2]]) cube(oled_pcb);
        for (su = [-1, 1], sv = [-1, 1]) translate([su*oled_hole[0], oled_vc + sv*oled_hole[1], tpf - 5]) cylinder(d = oled_hole_d, h = 10, $fn = 16);
    }
    color(C_GLASS) translate([-oled_glass[0]/2, pb + oled_glass_e, tg - oled_glass[2]]) cube(oled_glass);
    color(C_AA) translate([-oled_aa[0]/2, pb + oled_glass_e + oled_aa_e, tg + eps]) cube([oled_aa[0], oled_aa[1], 0.02]);
    // 4P 排針（朝後）＋母頭
    color(C_HDR) translate([-4*2.54/2, pb + 1.3 - 1.27, tpf - oled_pcb[2] - 2.5]) cube([4*2.54, 2.54, 2.5]);
    for (i = [0 : 3]) {
        color(C_PIN) translate([(i - 1.5)*2.54 - 0.32, pb + 1.3 - 0.32, tpf - oled_pcb[2] - 2.5 - 6]) cube([0.64, 0.64, 6 + 2.5 + oled_pcb[2] + 0.5]);
        color(C_DUP) translate([(i - 1.5)*2.54 - 1.25, pb + 1.3 - 1.25, tpf - oled_pcb[2] - 2.5 - dupont_len - 0.05]) cube([2.5, 2.5, dupont_len]);
    }
}

// ---------------- 50 mm 喇叭（軸 +X；框前面＝x_bf+0.2） ----------------
module speaker_ref() translate([x_ledge + 0.05, y_s, z_s]) rotate([0, 90, 0]) {
    color("#3c3f45") difference() { cylinder(d = sp_d - 0.1, h = sp_flange_t - 0.1); translate([0, 0, -1]) cylinder(d = sp_d - 6, h = 5); }   // 外框
    color("#26282c") translate([0, 0, -0.5]) difference() { cylinder(d1 = 20, d2 = sp_d - 5.4, h = sp_flange_t); translate([0, 0, 0.6]) cylinder(d1 = 18, d2 = sp_d - 7, h = sp_flange_t); }  // 振膜
    color("#3c3f45") translate([0, 0, -(sp_h - sp_flange_t - 7)]) cylinder(d1 = 24, d2 = sp_basket_d - 1, h = sp_h - sp_flange_t - 7);   // 盆架
    color(C_METAL) translate([0, 0, -(sp_h - sp_flange_t)]) cylinder(d = sp_mag_d, h = 7);   // 磁鐵
}

// ---------------- 12×12 觸控開關（坐在舌片上；按柱頂＝鈕柱尖 −0.05） ----------------
module switch_ref() translate([x_b, y_b, z_seat + shim_n*shim_t + 0.02]) {   // R2：坐在墊片上
    color("#202020") translate([-sw_body[0]/2, -sw_body[1]/2, 0.0]) cube([sw_body[0], sw_body[1], sw_body[2]]);
    color(C_METAL) translate([-sw_body[0]/2 + 0.3, -sw_body[1]/2 + 0.3, sw_body[2]]) cube([sw_body[0] - 0.6, sw_body[1] - 0.6, 0.3]);
    color("#5a5a5a") translate([0, 0, sw_body[2] + 0.3]) cylinder(d = sw_act_d, h = sw_h - sw_body[2] - 0.3 - 0.07);
    for (sx = [-1, 1], sy = [-1, 1]) color(C_METAL) translate([sx*sw_leg_px/2 - 0.35, sy*sw_leg_py/2 - 0.15, -3.5]) cube([0.7, 0.3, 3.5 + 1.0]);
}

// ---------------- 檢查用：USB 插頭（模具殼＋金屬段） ----------------
module usb_plug_ref(k = 0, grow = 0, pd = plug_ref) {
    dx = usb_dx[k];  plug = pd;
    color("#444") translate([x_c + dx - (plug[0] + grow)/2, y_pe + usb_over + 0.3, z_usb - (plug[1] + grow)/2]) cube([plug[0] + grow, 30, plug[1] + grow]);
    color(C_METAL) translate([x_c + dx - (usb_rec[0] - 0.6)/2, y_pe + usb_over - 6.2, z_usb - (usb_rec[2] - 0.8)/2]) cube([usb_rec[0] - 0.6, 6.5, usb_rec[2] - 0.8]);
}
