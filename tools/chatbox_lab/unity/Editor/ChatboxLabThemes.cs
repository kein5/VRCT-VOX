using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using B = ChatboxLabSceneBuilder;

// Zones made to look like common VRChat worlds: furnished rooms with ceilings
// and lamps, outdoor scenes under a sky, glowing signs and video screens, and
// mirrors. Many of them have world-info panels and menu boards with white text
// on a dark rounded panel, the hardest negatives for a chatbox detector.
//
// The speaker stands at the zone centre and the camera within ClearRadius of
// it, so everything taller than the floor stays outside that circle.
public static class ChatboxLabThemes
{
    public const int Count = 10;
    const float ClearRadius = 8.5f;
    const float RoomHalf = 12f;
    const float Ceiling = 5f;

    static readonly string[] InfoLines =
    {
        "ようこそ！ゆっくりしていってね", "ワールド説明", "このワールドは撮影OKです", "迷惑行為は禁止です", "ミラーは右側のボタンで切り替え",
        "BGM 音量", "毎週土曜 22:00 から集会", "初心者さん歓迎", "Quest対応", "Welcome to our world!", "Please be kind to everyone",
        "Mirror  HQ / LQ / OFF", "Video Player", "Event schedule", "Rules", "制作: chatbox lab", "ドリンク 300円", "本日のおすすめ",
        "フレンド募集中", "写真スポットはこちら", "→ 2F ラウンジ", "注意事項", "ポータルは奥にあります", "Updated 2026/11/01",
    };

    public static void Build(int theme, Transform zone, System.Random random)
    {
        switch (theme)
        {
            case 0: JapaneseRoom(zone, random); break;
            case 1: NightRooftop(zone, random); break;
            case 2: Club(zone, random); break;
            case 3: Cafe(zone, random); break;
            case 4: MirrorLounge(zone, random); break;
            case 5: Park(zone, random); break;
            case 6: Beach(zone, random); break;
            case 7: SciFiLobby(zone, random); break;
            case 8: Classroom(zone, random); break;
            default: AvatarGallery(zone, random); break;
        }
        var post = Post[theme];
        B.PostVolume(zone, $"theme{theme}", post[0], post[1], post[2], post[3], post[4]);
    }

    // Bloom, temperature, saturation, exposure, vignette for each theme.
    static readonly float[][] Post =
    {
        new[] { 2f, 15f, 5f, 0f, 0.3f }, new[] { 6f, -10f, 15f, 0.3f, 0.35f }, new[] { 8f, 0f, 20f, 0.2f, 0.4f },
        new[] { 2f, 20f, 0f, 0.1f, 0.25f }, new[] { 1.5f, 5f, 0f, 0f, 0.2f }, new[] { 1f, 0f, 10f, 0.2f, 0f },
        new[] { 4f, 25f, 15f, 0f, 0.3f }, new[] { 3f, -15f, -5f, -0.2f, 0.2f }, new[] { 1f, 5f, -5f, 0f, 0.1f },
        new[] { 3f, 0f, 5f, 0f, 0.35f },
    };

    // ---- zones -----------------------------------------------------------

    static void JapaneseRoom(Transform zone, System.Random random)
    {
        Room(zone, B.Textured("tatami", B.Tatami(random), 6f), B.Textured("woodwall", B.Planks(new Color(0.55f, 0.38f, 0.22f), random, vertical: true), 4f),
            B.Textured("ceilingwood", B.Planks(new Color(0.65f, 0.5f, 0.32f), random, vertical: false), 4f));
        var shoji = B.Textured("shoji", B.Shoji(), 1f);
        for (int i = 0; i < 4; i++)
            Prop(zone, "Shoji", new Vector3(-6f + i * 4f, 2.2f, RoomHalf - 0.2f), new Vector3(3.6f, 3.6f, 0.05f), shoji);
        Prop(zone, "LowTable", new Vector3(0f, 0.35f, 10f), new Vector3(3f, 0.1f, 1.5f), B.Solid("lacquer", new Color(0.25f, 0.08f, 0.05f), 0.7f));
        for (int i = 0; i < 6; i++)
            Lantern(zone, AtRing(i * 60f + 30f, 10.5f, 3.8f), new Color(1f, 0.75f, 0.45f));
        Scroll(zone, AtRing(-90f, RoomHalf - 0.25f, 2.6f), "一期一会");
        Scroll(zone, AtRing(90f, RoomHalf - 0.25f, 2.6f), "和");
        InfoPanels(zone, random, 2);
        B.Lamp(zone, new Color(1f, 0.85f, 0.65f), 1.2f, new Vector3(0f, Ceiling - 0.5f, 0f));
    }

    static void NightRooftop(Transform zone, System.Random random)
    {
        Sky(zone, "night", new Color(0.01f, 0.01f, 0.05f), new Color(0.12f, 0.08f, 0.25f), new Color(0.02f, 0.02f, 0.03f), stars: true, random);
        Floor(zone, B.Textured("concrete", B.Noise(new Color(0.35f, 0.35f, 0.37f), 0.12f, random), 8f), 40f);
        var railing = B.Solid("railing", new Color(0.6f, 0.6f, 0.65f), 0.6f);
        for (int i = 0; i < 4; i++)
        {
            var rotation = Quaternion.Euler(0f, i * 90f, 0f);
            Prop(zone, "Rail", rotation * new Vector3(0f, 1.1f, 14f), new Vector3(28f, 0.08f, 0.08f), railing).transform.localRotation = rotation;
        }
        var windows = B.Emissive("windows", B.Windows(random), Color.white, 1.2f, 0.6f);
        for (int i = 0; i < 14; i++)
        {
            float angle = i * (360f / 14f) + random.Next(-8, 8);
            float height = 8f + (float)random.NextDouble() * 26f;
            var position = AtRing(angle, 28f + (float)random.NextDouble() * 10f, height / 2f - 6f);
            Prop(zone, "Building", position, new Vector3(6f + random.Next(0, 5), height, 6f + random.Next(0, 5)), windows)
                .transform.localRotation = Quaternion.Euler(0f, angle, 0f);
        }
        string[] neon = { "ラーメン", "BAR", "カラオケ", "OPEN 24H", "居酒屋", "HOTEL", "CAFE", "ゲームセンター" };
        for (int i = 0; i < 6; i++)
            NeonSign(zone, AtRing(i * 60f + random.Next(0, 30), 13.5f, 2f + (float)random.NextDouble() * 2.5f), neon[random.Next(neon.Length)],
                Color.HSVToRGB((float)random.NextDouble(), 0.8f, 1f));
        B.Lamp(zone, new Color(0.5f, 0.6f, 1f), 0.6f, new Vector3(0f, 6f, 0f));
        InfoPanels(zone, random, 1);
    }

    static void Club(Transform zone, System.Random random)
    {
        Room(zone, B.Solid("clubfloor", new Color(0.03f, 0.03f, 0.04f), 0.9f), B.Solid("clubwall", new Color(0.04f, 0.03f, 0.06f), 0.3f),
            B.Solid("clubceiling", new Color(0.02f, 0.02f, 0.02f), 0.1f));
        for (int i = 0; i < 12; i++)
        {
            var color = i % 2 == 0 ? new Color(1f, 0.1f, 0.7f) : new Color(0.1f, 0.8f, 1f);
            var rotation = Quaternion.Euler(0f, (i % 4) * 90f, 0f);
            Prop(zone, "LedStrip", rotation * new Vector3(0f, 0.6f + (i / 4) * 1.4f, RoomHalf - 0.2f), new Vector3(20f, 0.08f, 0.05f),
                B.Emissive($"led{i % 2}", null, color, 3f)).transform.localRotation = rotation;
        }
        Screen(zone, new Vector3(0f, 2.7f, RoomHalf - 0.3f), Quaternion.identity, 9f, 4f, random, "♪ Now Playing: Night Drive");
        Prop(zone, "DJBooth", new Vector3(0f, 0.6f, 10f), new Vector3(4f, 1.2f, 1.2f), B.Solid("booth", new Color(0.1f, 0.1f, 0.12f), 0.6f));
        for (int i = 0; i < 2; i++)
            Prop(zone, "Speaker", new Vector3(i == 0 ? -5.5f : 5.5f, 1.5f, 10.5f), new Vector3(1.4f, 3f, 1.2f), B.Solid("speakerbox", new Color(0.05f, 0.05f, 0.05f), 0.2f));
        for (int i = 0; i < 4; i++)
        {
            var spot = new GameObject("Spot").AddComponent<Light>();
            spot.transform.SetParent(zone, false);
            spot.transform.localPosition = new Vector3(-6f + i * 4f, Ceiling - 0.3f, 6f);
            spot.transform.localRotation = Quaternion.Euler(70f + random.Next(-15, 15), random.Next(-30, 30), 0f);
            spot.type = LightType.Spot;
            spot.spotAngle = 35f;
            spot.range = 15f;
            spot.intensity = 4f;
            spot.color = Color.HSVToRGB((float)random.NextDouble(), 0.9f, 1f);
        }
        Sparkles(zone, new Vector3(0f, 3f, 9f), new Color(1f, 0.9f, 1f));
        B.Lamp(zone, new Color(0.6f, 0.2f, 1f), 1.2f, new Vector3(0f, Ceiling - 0.5f, 0f));
        InfoPanels(zone, random, 1);
    }

    static void Cafe(Transform zone, System.Random random)
    {
        Room(zone, B.Textured("cafefloor", B.Planks(new Color(0.45f, 0.3f, 0.18f), random, vertical: false), 5f),
            B.Textured("brick", B.Bricks(random), 4f), B.Solid("cafeceiling", new Color(0.9f, 0.88f, 0.82f), 0.1f));
        var wood = B.Textured("tablewood", B.Planks(new Color(0.5f, 0.33f, 0.2f), random, vertical: false), 1f);
        Prop(zone, "Counter", new Vector3(0f, 0.55f, 10.5f), new Vector3(10f, 1.1f, 1f), wood);
        for (int i = 0; i < 6; i++)
        {
            var center = AtRing(i * 60f + 15f, 10f, 0f);
            Prop(zone, "Table", center + Vector3.up * 0.75f, new Vector3(1.1f, 0.06f, 1.1f), wood);
            Prop(zone, "TableLeg", center + Vector3.up * 0.37f, new Vector3(0.1f, 0.75f, 0.1f), B.Solid("metal", new Color(0.2f, 0.2f, 0.2f), 0.7f));
            Pendant(zone, center + Vector3.up * 3.6f);
        }
        for (int i = 0; i < 4; i++)
            Plant(zone, AtRing(i * 90f + 45f, 11f, 0f), random);
        MenuBoard(zone, AtRing(-90f, RoomHalf - 0.2f, 2.4f), random);
        MenuBoard(zone, AtRing(180f, RoomHalf - 0.2f, 2.4f), random);
        InfoPanels(zone, random, 1);
        B.Lamp(zone, new Color(1f, 0.85f, 0.65f), 1.4f, new Vector3(0f, Ceiling - 0.5f, 0f));
    }

    static void MirrorLounge(Transform zone, System.Random random)
    {
        Room(zone, B.Textured("carpet", B.Noise(new Color(0.35f, 0.25f, 0.4f), 0.15f, random), 6f), B.Solid("loungewall", new Color(0.82f, 0.78f, 0.74f), 0.2f),
            B.Solid("loungeceiling", new Color(0.92f, 0.9f, 0.88f), 0.1f));
        var mirror = AssetDatabase.LoadAssetAtPath<GameObject>(B.MirrorPrefab);
        for (int i = 0; i < 2; i++)
        {
            var instance = (GameObject)PrefabUtility.InstantiatePrefab(mirror, zone);
            float angle = i == 0 ? 0f : 90f + random.Next(0, 2) * 180f;
            instance.transform.localPosition = AtRing(angle, RoomHalf - 0.2f, 2.2f);
            instance.transform.localRotation = Quaternion.Euler(0f, angle, 0f);
            instance.transform.localScale = new Vector3(5f, 3.2f, 1f);
        }
        var sofa = B.Solid("sofa", new Color(0.25f, 0.3f, 0.5f), 0.1f);
        for (int i = 0; i < 4; i++)
        {
            var rotation = Quaternion.Euler(0f, i * 90f + 45f, 0f);
            Prop(zone, "Sofa", rotation * new Vector3(0f, 0.4f, 10.5f), new Vector3(3f, 0.8f, 1f), sofa).transform.localRotation = rotation;
            Prop(zone, "SofaBack", rotation * new Vector3(0f, 0.9f, 11f), new Vector3(3f, 1f, 0.25f), sofa).transform.localRotation = rotation;
        }
        Panel(zone, AtRing(-30f, RoomHalf - 0.25f, 1.6f), 2.2f, 0.9f, new Color(0.1f, 0.1f, 0.12f, 0.85f),
            new[] { "Mirror", "HQ   LQ   OFF" }, Color.white, 0);
        InfoPanels(zone, random, 2);
        B.Lamp(zone, new Color(1f, 0.95f, 0.9f), 1.6f, new Vector3(0f, Ceiling - 0.5f, 0f));
    }

    static void Park(Transform zone, System.Random random)
    {
        Sky(zone, "day", new Color(0.25f, 0.5f, 0.95f), new Color(0.75f, 0.88f, 1f), new Color(0.4f, 0.45f, 0.4f), stars: false, random);
        Floor(zone, B.Textured("grass", B.Noise(new Color(0.3f, 0.55f, 0.2f), 0.2f, random), 12f), 60f);
        Prop(zone, "Path", new Vector3(0f, 0.01f, 0f), new Vector3(3f, 0.02f, 60f), B.Textured("gravel", B.Noise(new Color(0.65f, 0.6f, 0.5f), 0.15f, random), 6f));
        for (int i = 0; i < 18; i++)
            Tree(zone, AtRing(random.Next(0, 360), 11f + (float)random.NextDouble() * 18f, 0f), random);
        var bench = B.Textured("benchwood", B.Planks(new Color(0.55f, 0.35f, 0.2f), random, vertical: false), 1f);
        for (int i = 0; i < 3; i++)
            Prop(zone, "Bench", AtRing(i * 120f + 20f, 9.5f, 0.45f), new Vector3(2f, 0.1f, 0.5f), bench);
        Sign(zone, AtRing(160f, 9.5f, 1.4f), "← 展望台  /  池 →", new Color(0.35f, 0.25f, 0.15f), Color.white);
        InfoPanels(zone, random, 1);
    }

    static void Beach(Transform zone, System.Random random)
    {
        Sky(zone, "sunset", new Color(0.2f, 0.15f, 0.45f), new Color(1f, 0.55f, 0.3f), new Color(0.1f, 0.2f, 0.35f), stars: false, random);
        Floor(zone, B.Textured("sand", B.Noise(new Color(0.85f, 0.75f, 0.55f), 0.1f, random), 10f), 60f);
        Prop(zone, "Sea", new Vector3(0f, 0.05f, 30f), new Vector3(70f, 0.02f, 30f), B.Solid("sea", new Color(0.1f, 0.3f, 0.45f), 0.95f));
        for (int i = 0; i < 8; i++)
            Palm(zone, AtRing(random.Next(100, 260), 10f + (float)random.NextDouble() * 12f, 0f), random);
        for (int i = 0; i < 3; i++)
        {
            var position = AtRing(i * 50f - 50f, 10f, 0f);
            Prop(zone, "UmbrellaPole", position + Vector3.up * 1.2f, new Vector3(0.06f, 2.4f, 0.06f), B.Solid("pole", Color.white, 0.3f));
            Prop(zone, "Umbrella", position + Vector3.up * 2.4f, new Vector3(2.4f, 0.15f, 2.4f),
                B.Solid($"umbrella{i}", Color.HSVToRGB(i / 3f, 0.7f, 0.95f), 0.2f), PrimitiveType.Sphere);
        }
        InfoPanels(zone, random, 1);
    }

    static void SciFiLobby(Transform zone, System.Random random)
    {
        Room(zone, B.Solid("scififloor", new Color(0.7f, 0.72f, 0.76f), 0.6f), B.Solid("scifiwall", new Color(0.9f, 0.92f, 0.95f), 0.5f),
            B.Solid("scificeiling", new Color(0.8f, 0.82f, 0.85f), 0.3f));
        for (int i = 0; i < 8; i++)
        {
            var rotation = Quaternion.Euler(0f, i * 45f, 0f);
            if (i % 2 == 0)
                Prop(zone, "Trim", rotation * new Vector3(0f, 0.15f, RoomHalf - 0.25f), new Vector3(22f, 0.06f, 0.05f), B.Emissive("cyan", null, new Color(0.2f, 0.9f, 1f), 2.5f))
                    .transform.localRotation = rotation;
            Prop(zone, "Pillar", AtRing(i * 45f + 22.5f, 10.5f, Ceiling / 2f), new Vector3(0.8f, Ceiling, 0.8f), B.Solid("pillar", new Color(0.75f, 0.78f, 0.82f), 0.6f));
        }
        string[][] holograms =
        {
            new[] { "WORLD INFO", "Players: 2 / 32", "Region: JP" },
            new[] { "ANNOUNCEMENT", "メンテナンス 23:00-24:00", "Thank you for visiting" },
            new[] { "SETTINGS", "Post Processing  ON", "Bloom  ■■■□□" },
        };
        for (int i = 0; i < 3; i++)
            Panel(zone, AtRing(i * 120f + random.Next(-20, 20), RoomHalf - 1f, 2f + (float)random.NextDouble()), 3f, 1.6f,
                new Color(0.1f, 0.6f, 0.9f, 0.35f), holograms[i], new Color(0.8f, 1f, 1f), 1);
        Screen(zone, AtRing(200f, RoomHalf - 0.6f, 2.6f), FacingCenter(AtRing(200f, 1f, 0f)), 6f, 3.2f, random, "LIVE 配信中");
        B.Lamp(zone, Color.white, 1.1f, new Vector3(0f, Ceiling - 0.5f, 0f));
        InfoPanels(zone, random, 1);
    }

    static void Classroom(Transform zone, System.Random random)
    {
        Room(zone, B.Textured("classfloor", B.Planks(new Color(0.6f, 0.45f, 0.3f), random, vertical: false), 6f), B.Solid("classwall", new Color(0.92f, 0.9f, 0.82f), 0.1f),
            B.Solid("classceiling", Color.white, 0.1f));
        var board = B.Solid("blackboard", new Color(0.12f, 0.25f, 0.18f), 0.1f);
        Prop(zone, "Blackboard", new Vector3(0f, 2.2f, RoomHalf - 0.2f), new Vector3(8f, 2.4f, 0.05f), board);
        string[] chalk = { "今日の予定", "1. 自己紹介", "2. ワールド巡り", "宿題: アバター改変" };
        for (int i = 0; i < chalk.Length; i++)
            B.Text(zone, chalk[i], new Vector3(-3.4f, 3f - i * 0.5f, RoomHalf - 0.3f), Quaternion.identity, 0.32f, new Color(0.95f, 0.95f, 0.9f),
                B.Fonts[1], TextAnchor.MiddleLeft);
        var books = B.Textured("books", B.Books(random), 1f);
        for (int i = 0; i < 3; i++)
        {
            float angle = 90f + i * 90f;
            Prop(zone, "Shelf", AtRing(angle, RoomHalf - 0.5f, 1.6f), new Vector3(7f, 3.2f, 0.6f), books).transform.localRotation = Quaternion.Euler(0f, angle, 0f);
        }
        var desk = B.Textured("deskwood", B.Planks(new Color(0.7f, 0.55f, 0.35f), random, vertical: false), 1f);
        for (int i = 0; i < 8; i++)
            Prop(zone, "Desk", AtRing(i * 45f, 9.5f, 0.7f), new Vector3(1.2f, 0.06f, 0.6f), desk);
        for (int i = 0; i < 3; i++)
            Prop(zone, "Window", AtRing(-90f, RoomHalf - 0.2f, 2.6f) + new Vector3(0f, 0f, -6f + i * 6f), new Vector3(0.05f, 2f, 3f),
                B.Emissive("window", null, new Color(0.85f, 0.95f, 1f), 1.2f));
        B.Lamp(zone, Color.white, 1.2f, new Vector3(0f, Ceiling - 0.5f, 0f));
        InfoPanels(zone, random, 1);
    }

    static void AvatarGallery(Transform zone, System.Random random)
    {
        Room(zone, B.Textured("galleryfloor", B.Tiles(new Color(0.2f, 0.2f, 0.22f), new Color(0.26f, 0.26f, 0.28f)), 8f),
            B.Solid("gallerywall", new Color(0.12f, 0.12f, 0.15f), 0.2f), B.Solid("galleryceiling", new Color(0.08f, 0.08f, 0.1f), 0.1f));
        string[] names = { "Rusk", "Manuka", "Karin", "Lime", "Shinano", "Moe", "Chiffon", "Kikyo", "Sio", "Mishe", "Lasyusha", "Maya" };
        for (int i = 0; i < 12; i++)
        {
            float angle = i * 30f;
            var position = AtRing(angle, 10.5f, 0f);
            var rotation = Quaternion.Euler(0f, angle, 0f);
            Prop(zone, "Pedestal", position + Vector3.up * 0.5f, new Vector3(1.2f, 1f, 1.2f), B.Solid("pedestal", new Color(0.3f, 0.3f, 0.34f), 0.6f), PrimitiveType.Cylinder);
            var thumbnail = Prop(zone, "Thumbnail", position + Vector3.up * 2.1f, new Vector3(1.2f, 0.9f, 1f),
                B.Emissive($"thumb{i % 6}", B.Thumbnail(random), Color.white, 1f), PrimitiveType.Quad);
            thumbnail.transform.localRotation = rotation;
            Panel(zone, position + Vector3.up * 1.35f, 1.3f, 0.32f, new Color(0.08f, 0.08f, 0.1f, 0.8f), new[] { names[i] }, Color.white, i % 3, rotation);
        }
        B.Lamp(zone, new Color(0.9f, 0.9f, 1f), 1.5f, new Vector3(0f, Ceiling - 0.5f, 0f));
        InfoPanels(zone, random, 2);
    }

    // ---- building blocks -------------------------------------------------

    static Vector3 AtRing(float angle, float radius, float height) =>
        Quaternion.Euler(0f, angle, 0f) * Vector3.forward * radius + Vector3.up * height;

    static Quaternion FacingCenter(Vector3 local)
    {
        var flat = new Vector3(local.x, 0f, local.z);
        return Quaternion.LookRotation(flat.sqrMagnitude > 0f ? flat : Vector3.forward);
    }

    static GameObject Prop(Transform zone, string name, Vector3 local, Vector3 size, Material material, PrimitiveType type = PrimitiveType.Cube)
    {
        var flat = new Vector3(local.x, 0f, local.z);
        float bottom = local.y - Mathf.Abs(size.y) / 2f, top = local.y + Mathf.Abs(size.y) / 2f;
        if (top > 0.1f && bottom < 2.6f && flat.magnitude < ClearRadius)
            Debug.LogWarning($"{zone.name}/{name} stands inside the camera circle");
        var prop = GameObject.CreatePrimitive(type);
        prop.name = name;
        prop.transform.SetParent(zone, false);
        prop.transform.localPosition = local;
        prop.transform.localScale = size;
        prop.GetComponent<Renderer>().sharedMaterial = material;
        Object.DestroyImmediate(prop.GetComponent<Collider>());
        return prop;
    }

    static void Floor(Transform zone, Material material, float size)
    {
        B.Box(zone, "Floor", new Vector3(0f, -0.25f, 0f), new Vector3(size, 0.5f, size), material);
    }

    static void Room(Transform zone, Material floor, Material wall, Material ceiling)
    {
        Floor(zone, floor, RoomHalf * 2f + 1f);
        B.Box(zone, "WallN", new Vector3(0f, Ceiling / 2f, RoomHalf), new Vector3(RoomHalf * 2f, Ceiling, 0.3f), wall);
        B.Box(zone, "WallS", new Vector3(0f, Ceiling / 2f, -RoomHalf), new Vector3(RoomHalf * 2f, Ceiling, 0.3f), wall);
        B.Box(zone, "WallE", new Vector3(RoomHalf, Ceiling / 2f, 0f), new Vector3(0.3f, Ceiling, RoomHalf * 2f), wall);
        B.Box(zone, "WallW", new Vector3(-RoomHalf, Ceiling / 2f, 0f), new Vector3(0.3f, Ceiling, RoomHalf * 2f), wall);
        B.Box(zone, "Ceiling", new Vector3(0f, Ceiling + 0.15f, 0f), new Vector3(RoomHalf * 2f, 0.3f, RoomHalf * 2f), ceiling);
        // Recessed ceiling lights, as most rooms have.
        var panel = B.Emissive("ceilinglight", null, new Color(1f, 0.97f, 0.9f), 1.5f);
        for (int x = -1; x <= 1; x++)
            for (int z = -1; z <= 1; z++)
                Prop(zone, "CeilingLight", new Vector3(x * 7f, Ceiling - 0.01f, z * 7f), new Vector3(1.6f, 0.02f, 1.6f), panel);
    }

    static void Sky(Transform zone, string name, Color top, Color horizon, Color bottom, bool stars, System.Random random)
    {
        var dome = new GameObject("Sky");
        dome.transform.SetParent(zone, false);
        dome.transform.localScale = Vector3.one * 90f;
        dome.AddComponent<MeshFilter>().sharedMesh = B.InvertedSphere();
        var renderer = dome.AddComponent<MeshRenderer>();
        renderer.sharedMaterial = B.Unlit($"sky_{name}", B.Gradient(top, horizon, bottom, stars, random));
        renderer.shadowCastingMode = ShadowCastingMode.Off;
        renderer.receiveShadows = false;
    }

    static void Lantern(Transform zone, Vector3 local, Color color)
    {
        Prop(zone, "Lantern", local, new Vector3(0.45f, 0.6f, 0.45f), B.Emissive("lantern", null, color, 1.6f), PrimitiveType.Sphere);
    }

    static void Pendant(Transform zone, Vector3 local)
    {
        Prop(zone, "PendantCord", local + Vector3.up * 0.7f, new Vector3(0.02f, 1.4f, 0.02f), B.Solid("cord", Color.black, 0.1f));
        Prop(zone, "Pendant", local, new Vector3(0.4f, 0.3f, 0.4f), B.Emissive("bulb", null, new Color(1f, 0.8f, 0.5f), 2f), PrimitiveType.Sphere);
    }

    static void Scroll(Transform zone, Vector3 local, string text)
    {
        Prop(zone, "Scroll", local, new Vector3(0.9f, 2f, 0.02f), B.Solid("paper", new Color(0.93f, 0.9f, 0.82f), 0.05f)).transform.localRotation = FacingCenter(local);
        B.Text(zone, string.Join("\n", text.ToCharArray()), local - FacingCenter(local) * Vector3.forward * 0.03f, FacingCenter(local), 0.45f,
            new Color(0.1f, 0.1f, 0.1f), B.Fonts[2], TextAnchor.MiddleCenter);
    }

    static void NeonSign(Transform zone, Vector3 local, string text, Color color)
    {
        var rotation = FacingCenter(local);
        Prop(zone, "NeonBack", local + rotation * Vector3.forward * 0.05f, new Vector3(0.45f * text.Length + 0.6f, 1f, 0.05f),
            B.Solid("neonback", new Color(0.03f, 0.03f, 0.04f), 0.3f)).transform.localRotation = rotation;
        B.Text(zone, text, local - rotation * Vector3.forward * 0.02f, rotation, 0.6f, color * 1.2f, B.Fonts[0], TextAnchor.MiddleCenter);
    }

    static void Sign(Transform zone, Vector3 local, string text, Color board, Color ink)
    {
        var rotation = FacingCenter(local);
        Prop(zone, "SignBoard", local, new Vector3(0.22f * text.Length + 0.4f, 0.6f, 0.05f), B.Solid($"board{board.GetHashCode() & 0xff}", board, 0.2f))
            .transform.localRotation = rotation;
        B.Text(zone, text, local - rotation * Vector3.forward * 0.04f, rotation, 0.3f, ink, B.Fonts[0], TextAnchor.MiddleCenter);
    }

    static void MenuBoard(Transform zone, Vector3 local, System.Random random)
    {
        string[] items = { "MENU", "コーヒー  ¥400", "カフェラテ  ¥480", "抹茶ラテ  ¥520", "チーズケーキ  ¥450", "本日のおすすめ: パンケーキ" };
        Panel(zone, local, 2.6f, 2f, new Color(0.08f, 0.08f, 0.08f, 0.92f), items, new Color(0.95f, 0.95f, 0.9f), random.Next(3));
    }

    // Dark rounded panels with lines of white text, as world-info boards and
    // menus look. Next to a real chatbox they are the main source of confusion.
    static void InfoPanels(Transform zone, System.Random random, int count)
    {
        for (int i = 0; i < count; i++)
        {
            int lines = 1 + random.Next(4);
            var text = new string[lines];
            for (int l = 0; l < lines; l++)
                text[l] = InfoLines[random.Next(InfoLines.Length)];
            float angle = random.Next(0, 360);
            var color = random.Next(3) == 0 ? new Color(0.95f, 0.95f, 0.95f, 0.85f) : new Color(0.08f, 0.08f, 0.1f, 0.6f + 0.3f * (float)random.NextDouble());
            var ink = color.r > 0.5f ? new Color(0.1f, 0.1f, 0.1f) : Color.white;
            Panel(zone, AtRing(angle, ClearRadius + 0.5f + (float)random.NextDouble() * 2.5f, 1.6f + (float)random.NextDouble() * 1.4f),
                1.6f + 0.1f * text[0].Length, 0.35f + 0.33f * lines, color, text, ink, random.Next(3));
        }
    }

    static void Panel(Transform zone, Vector3 local, float width, float height, Color color, string[] lines, Color ink, int font, Quaternion? facing = null)
    {
        var rotation = facing ?? FacingCenter(local);
        var panel = GameObject.CreatePrimitive(PrimitiveType.Quad);
        panel.name = "Panel";
        panel.transform.SetParent(zone, false);
        panel.transform.localPosition = local;
        panel.transform.localRotation = rotation;
        panel.transform.localScale = new Vector3(width, height, 1f);
        Object.DestroyImmediate(panel.GetComponent<Collider>());
        panel.GetComponent<Renderer>().sharedMaterial = B.PanelMaterial(color);
        float size = Mathf.Min(0.28f, height / (lines.Length + 0.8f));
        for (int i = 0; i < lines.Length; i++)
        {
            float y = (lines.Length - 1) / 2f * size * 1.15f - i * size * 1.15f;
            B.Text(zone, lines[i], local + rotation * new Vector3(0f, y, -0.02f), rotation, size, ink, B.Fonts[font], TextAnchor.MiddleCenter);
        }
    }

    static void Screen(Transform zone, Vector3 local, Quaternion rotation, float width, float height, System.Random random, string caption)
    {
        var screen = Prop(zone, "Screen", local, new Vector3(width, height, 1f), B.Emissive("screen", B.VideoFrame(random), Color.white, 1.2f), PrimitiveType.Quad);
        screen.transform.localRotation = rotation;
        B.Text(zone, caption, local + rotation * new Vector3(0f, -height / 2f + 0.35f, -0.02f), rotation, 0.3f, Color.white, B.Fonts[0], TextAnchor.MiddleCenter);
    }

    static void Plant(Transform zone, Vector3 local, System.Random random)
    {
        Prop(zone, "Pot", local + Vector3.up * 0.3f, new Vector3(0.6f, 0.3f, 0.6f), B.Solid("pot", new Color(0.6f, 0.35f, 0.25f), 0.2f), PrimitiveType.Cylinder);
        var leaves = B.Textured("leaves", B.Noise(new Color(0.2f, 0.45f, 0.18f), 0.25f, random), 2f);
        for (int i = 0; i < 3; i++)
            Prop(zone, "Leaves", local + new Vector3((float)random.NextDouble() * 0.4f - 0.2f, 1f + i * 0.35f, (float)random.NextDouble() * 0.4f - 0.2f),
                Vector3.one * (0.9f - i * 0.2f), leaves, PrimitiveType.Sphere);
    }

    static void Tree(Transform zone, Vector3 local, System.Random random)
    {
        float height = 3f + (float)random.NextDouble() * 3f;
        Prop(zone, "Trunk", local + Vector3.up * height / 2f, new Vector3(0.35f, height / 2f, 0.35f), B.Solid("trunk", new Color(0.35f, 0.23f, 0.14f), 0.1f), PrimitiveType.Cylinder);
        var leaves = B.Textured("treeleaves", B.Noise(new Color(0.18f, 0.42f, 0.15f), 0.25f, random), 2f);
        for (int i = 0; i < 3; i++)
            Prop(zone, "Canopy", local + new Vector3((float)random.NextDouble() - 0.5f, height + i * 0.6f, (float)random.NextDouble() - 0.5f),
                Vector3.one * (2.8f - i * 0.6f), leaves, PrimitiveType.Sphere);
    }

    static void Palm(Transform zone, Vector3 local, System.Random random)
    {
        float height = 4f + (float)random.NextDouble() * 2f;
        Prop(zone, "PalmTrunk", local + Vector3.up * height / 2f, new Vector3(0.3f, height / 2f, 0.3f), B.Solid("palmtrunk", new Color(0.5f, 0.38f, 0.25f), 0.1f), PrimitiveType.Cylinder);
        var leaf = B.Solid("palmleaf", new Color(0.2f, 0.5f, 0.2f), 0.2f);
        for (int i = 0; i < 6; i++)
            Prop(zone, "Frond", local + Vector3.up * height + Quaternion.Euler(0f, i * 60f, 0f) * Vector3.forward * 1f, new Vector3(0.5f, 0.08f, 2.2f), leaf)
                .transform.localRotation = Quaternion.Euler(20f, i * 60f, 0f);
    }

    static void Sparkles(Transform zone, Vector3 local, Color color)
    {
        var holder = new GameObject("Sparkles");
        holder.transform.SetParent(zone, false);
        holder.transform.localPosition = local;
        var particles = holder.AddComponent<ParticleSystem>();
        var main = particles.main;
        main.startLifetime = 3f;
        main.startSpeed = 0.4f;
        main.startSize = 0.08f;
        main.startColor = color;
        main.maxParticles = 300;
        var shape = particles.shape;
        shape.shapeType = ParticleSystemShapeType.Box;
        shape.scale = new Vector3(10f, 3f, 2f);
        var emission = particles.emission;
        emission.rateOverTime = 60f;
        holder.GetComponent<ParticleSystemRenderer>().sharedMaterial = B.ParticleMaterial(color);
    }
}
