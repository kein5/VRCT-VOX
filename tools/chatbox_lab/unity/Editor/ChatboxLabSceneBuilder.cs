using System.Collections.Generic;
using System.IO;
using UdonSharp;
using UdonSharpEditor;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.PostProcessing;
using VRC.SDK3.Components;

// Builds the chatbox photo world from code, so it can be rebuilt and reviewed.
// The first zones give the chatbox plain backgrounds and light: dark and
// bright rooms, open sky, busy textures, coloured neon, and signs with text as
// hard negatives. The themed zones after them (ChatboxLabThemes) look like
// common VRChat worlds. No third-party assets are used apart from the OFL
// fonts in Assets/ChatboxLab/Fonts.
public static class ChatboxLabSceneBuilder
{
    public const string Root = "Assets/ChatboxLab";
    public const string ScenePath = Root + "/ChatboxLab.unity";
    const string Generated = Root + "/Generated";
    const string FontFolder = Root + "/Fonts";
    const string WorldPrefab = "Packages/com.vrchat.worlds/Samples/UdonExampleScene/Prefabs/VRCWorld.prefab";
    public const string MirrorPrefab = "Packages/com.vrchat.worlds/Samples/UdonExampleScene/Prefabs/VRCMirror.prefab";
    // Outdoor zones have a sky dome of 45 m radius, so zones keep 100 m apart.
    const float Spacing = 100f;
    const float RoomSize = 24f;
    const float WallHeight = 8f;
    const int PlainZones = 8;
    // An unnamed layer for the post-processing volumes, as world creators do.
    public const int PostLayer = 22;
    const string PostResources = "Packages/com.unity.postprocessing/PostProcessing/PostProcessResources.asset";

    static readonly string[] SignWords =
    {
        "OPEN", "WELCOME", "EXIT", "STAGE", "CAFE", "MUSIC", "EVENT 21:00", "NO SMOKING", "LOBBY",
        "VRChat", "Hello World", "1F", "B2", "SALE 50%", "Mirror", "Quest OK", "PC ONLY", "DJ BOOTH",
        "ようこそ", "集会所", "ミラー", "撮影OK", "注意", "出口",
    };
    static readonly string[] FontFiles = { "MPLUS1p-Regular.ttf", "ZenKakuGothicNew-Regular.ttf", "BIZUDPGothic-Regular.ttf" };

    const string ScriptPath = Root + "/ChatboxLabDirector.cs";
    const string ProgramPath = Root + "/ChatboxLabDirector.asset";

    public static Font[] Fonts;
    static readonly Dictionary<string, Material> Materials = new Dictionary<string, Material>();
    static readonly Dictionary<Font, Material> TextMaterials = new Dictionary<Font, Material>();
    static Shader textShader, panelShader;
    static Texture2D roundedPanel;
    static Mesh invertedSphere;

    // U# compiles a new program asset asynchronously, so create it in a separate
    // step (or editor session) before building the scene.
    [MenuItem("VRCT-VOX/Prepare Chatbox Lab Program")]
    public static void PrepareProgram()
    {
        if (AssetDatabase.LoadAssetAtPath<UdonSharpProgramAsset>(ProgramPath) != null) return;
        var program = ScriptableObject.CreateInstance<UdonSharpProgramAsset>();
        program.sourceCsScript = AssetDatabase.LoadAssetAtPath<MonoScript>(ScriptPath);
        AssetDatabase.CreateAsset(program, ProgramPath);
        AssetDatabase.SaveAssets();
        UdonSharpProgramAsset.CompileAllCsPrograms(true);
    }

    [MenuItem("VRCT-VOX/Build Chatbox Lab Scene")]
    public static void BuildScene()
    {
        if (AssetDatabase.LoadAssetAtPath<UdonSharpProgramAsset>(ProgramPath) == null)
        {
            PrepareProgram();
            throw new System.InvalidOperationException("Created the U# program asset; build the scene again once it has compiled.");
        }
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        // Everything generated is made again, so stale materials cannot linger.
        AssetDatabase.DeleteAsset(Generated);
        Directory.CreateDirectory(Generated);
        AssetDatabase.Refresh();
        Materials.Clear();
        TextMaterials.Clear();
        textShader = panelShader = null;
        roundedPanel = null;
        invertedSphere = null;
        LoadFonts();

        RenderSettings.ambientMode = AmbientMode.Trilight;
        RenderSettings.ambientSkyColor = new Color(0.55f, 0.6f, 0.7f);
        RenderSettings.ambientEquatorColor = new Color(0.4f, 0.4f, 0.4f);
        RenderSettings.ambientGroundColor = new Color(0.2f, 0.2f, 0.2f);

        var sun = new GameObject("Sun").AddComponent<Light>();
        sun.type = LightType.Directional;
        sun.intensity = 1.0f;
        sun.shadows = LightShadows.Soft;
        sun.transform.rotation = Quaternion.Euler(50f, -30f, 0f);

        var random = new System.Random(20261101);
        var zones = new Transform[PlainZones + ChatboxLabThemes.Count];
        for (int i = 0; i < zones.Length; i++)
        {
            var zone = new GameObject($"Zone{i}").transform;
            zone.position = new Vector3(i * Spacing, 0f, 0f);
            if (i < PlainZones)
                BuildPlainZone(i, zone, random);
            else
                ChatboxLabThemes.Build(i - PlainZones, zone, random);
            zones[i] = zone;
        }

        var world = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(WorldPrefab));
        world.transform.position = zones[0].position;
        world.GetComponent<VRCSceneDescriptor>().ReferenceCamera = ReferenceCamera();

        var director = BuildDirector(zones);
        EditorSceneManager.SaveScene(scene, ScenePath);
        EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
        AssetDatabase.SaveAssets();
        Debug.Log($"Chatbox lab scene built with {zones.Length} zones and director {director.name}");
    }

    static void LoadFonts()
    {
        Fonts = new Font[FontFiles.Length];
        for (int i = 0; i < FontFiles.Length; i++)
            Fonts[i] = AssetDatabase.LoadAssetAtPath<Font>($"{FontFolder}/{FontFiles[i]}");
        if (System.Array.Exists(Fonts, font => font == null))
            Debug.LogWarning($"Copy {string.Join(", ", FontFiles)} to {FontFolder} for Japanese text; using the built-in font instead.");
        for (int i = 0; i < Fonts.Length; i++)
            Fonts[i] = Fonts[i] != null ? Fonts[i] : Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
    }

    static void BuildPlainZone(int index, Transform zone, System.Random random)
    {
        Box(zone, "Floor", new Vector3(0f, -0.25f, 0f), new Vector3(RoomSize + 6f, 0.5f, RoomSize + 6f),
            Solid($"floor{index % 3}", new[] { new Color(0.35f, 0.35f, 0.35f), new Color(0.6f, 0.55f, 0.45f), new Color(0.2f, 0.25f, 0.3f) }[index % 3]));

        Material wall = null;
        bool walls = true;
        switch (index)
        {
            case 0: wall = Solid("dark", new Color(0.08f, 0.08f, 0.09f)); Lamp(zone, new Color(1f, 0.95f, 0.85f), 0.8f); break;
            case 1: wall = Solid("bright", new Color(0.95f, 0.95f, 0.95f)); Lamp(zone, Color.white, 2.5f); break;
            case 2: walls = false; break;
            case 3: wall = Textured("stripes", Stripes()); break;
            case 4: wall = Textured("clutter", Clutter(random)); break;
            case 5:
                wall = Solid("neon", new Color(0.02f, 0.02f, 0.03f));
                Lamp(zone, new Color(1f, 0.2f, 0.8f), 3f, new Vector3(-6f, 4f, 4f));
                Lamp(zone, new Color(0.1f, 0.8f, 1f), 3f, new Vector3(6f, 4f, -4f));
                break;
            case 6: wall = Solid("green", new Color(0.18f, 0.4f, 0.22f)); break;
            default: wall = Solid("warm", new Color(0.85f, 0.5f, 0.25f)); Lamp(zone, new Color(1f, 0.8f, 0.6f), 1.5f); break;
        }
        if (walls)
        {
            float half = RoomSize / 2f;
            Box(zone, "WallN", new Vector3(0f, WallHeight / 2f, half), new Vector3(RoomSize, WallHeight, 0.3f), wall);
            Box(zone, "WallS", new Vector3(0f, WallHeight / 2f, -half), new Vector3(RoomSize, WallHeight, 0.3f), wall);
            Box(zone, "WallE", new Vector3(half, WallHeight / 2f, 0f), new Vector3(0.3f, WallHeight, RoomSize), wall);
            Box(zone, "WallW", new Vector3(-half, WallHeight / 2f, 0f), new Vector3(0.3f, WallHeight, RoomSize), wall);
        }
        // Signs are text that is not a chatbox; the detector must learn to skip them.
        for (int s = 0; s < 6; s++)
        {
            float angle = s * 60f + random.Next(0, 30);
            var rotation = Quaternion.Euler(0f, angle, 0f);
            var local = rotation * Vector3.forward * (RoomSize / 2f - 0.4f) + Vector3.up * (1.5f + (float)random.NextDouble() * 3f);
            Sign(zone, SignWords[random.Next(SignWords.Length)], local, rotation, random);
        }
    }

    public static GameObject Box(Transform parent, string name, Vector3 local, Vector3 size, Material material)
    {
        var box = GameObject.CreatePrimitive(PrimitiveType.Cube);
        box.name = name;
        box.transform.SetParent(parent, false);
        box.transform.localPosition = local;
        box.transform.localScale = size;
        box.GetComponent<Renderer>().sharedMaterial = material;
        return box;
    }

    public static void Lamp(Transform zone, Color color, float intensity, Vector3? local = null)
    {
        var lamp = new GameObject("Lamp").AddComponent<Light>();
        lamp.transform.SetParent(zone, false);
        lamp.transform.localPosition = local ?? new Vector3(0f, 6f, 0f);
        lamp.type = LightType.Point;
        lamp.range = 25f;
        lamp.color = color;
        lamp.intensity = intensity;
    }

    static void Sign(Transform zone, string text, Vector3 local, Quaternion rotation, System.Random random)
    {
        var board = GameObject.CreatePrimitive(PrimitiveType.Quad);
        board.name = "Sign";
        board.transform.SetParent(zone, false);
        board.transform.localPosition = local;
        board.transform.localRotation = rotation;
        board.transform.localScale = new Vector3(0.35f * text.Length + 0.6f, 0.9f, 1f);
        Object.DestroyImmediate(board.GetComponent<Collider>());
        bool light = random.Next(2) == 0;
        board.GetComponent<Renderer>().sharedMaterial = Solid(light ? "sign_light" : "sign_dark", light ? new Color(0.9f, 0.88f, 0.8f) : new Color(0.1f, 0.1f, 0.15f));
        Text(zone, text, local + rotation * new Vector3(0f, 0f, -0.01f), rotation, 0.55f,
            light ? new Color(0.1f, 0.1f, 0.1f) : new Color(0.95f, 0.95f, 0.9f), Fonts[random.Next(Fonts.Length)], TextAnchor.MiddleCenter);
    }

    // 3D text that is hidden behind walls. Unity's default font material draws
    // over everything, so signs from other zones showed through.
    public static TextMesh Text(Transform zone, string text, Vector3 local, Quaternion rotation, float height, Color color, Font font, TextAnchor anchor)
    {
        var label = new GameObject("Text").AddComponent<TextMesh>();
        label.transform.SetParent(zone, false);
        label.transform.localPosition = local;
        label.transform.localRotation = rotation;
        label.font = font;
        label.text = text;
        label.anchor = anchor;
        label.alignment = anchor == TextAnchor.MiddleLeft ? TextAlignment.Left : TextAlignment.Center;
        label.fontSize = 64;
        // A line is about fontSize * characterSize / 10 units high.
        label.characterSize = height * 10f / label.fontSize;
        label.color = color;
        label.GetComponent<MeshRenderer>().sharedMaterial = TextMaterial(font);
        return label;
    }

    static Material TextMaterial(Font font)
    {
        if (TextMaterials.TryGetValue(font, out var material)) return material;
        material = new Material(TextShader()) { mainTexture = font.material.mainTexture, renderQueue = 3001 };
        AssetDatabase.CreateAsset(material, $"{Generated}/text_{font.name}.mat");
        TextMaterials[font] = material;
        return material;
    }

    static Shader TextShader() => textShader ??= WriteShader("LabText", "ChatboxLab/Text", "fixed4 c = i.color; c.a *= tex2D(_MainTex, i.uv).a; return c;");

    static Shader PanelShader() => panelShader ??= WriteShader("LabPanel", "ChatboxLab/Panel", "fixed4 c = _Color; c.a *= tex2D(_MainTex, i.uv).a; return c;");

    static Shader WriteShader(string file, string name, string fragment)
    {
        string path = $"{Generated}/{file}.shader";
        File.WriteAllText(path, $@"Shader ""{name}""
{{
    Properties {{ _MainTex (""Texture"", 2D) = ""white"" {{}} _Color (""Color"", Color) = (1,1,1,1) }}
    SubShader
    {{
        Tags {{ ""Queue""=""Transparent"" ""RenderType""=""Transparent"" ""IgnoreProjector""=""True"" }}
        Lighting Off Cull Off ZWrite Off ZTest LEqual
        Blend SrcAlpha OneMinusSrcAlpha
        Pass
        {{
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include ""UnityCG.cginc""
            sampler2D _MainTex; float4 _MainTex_ST; fixed4 _Color;
            struct appdata {{ float4 vertex : POSITION; fixed4 color : COLOR; float2 uv : TEXCOORD0; UNITY_VERTEX_INPUT_INSTANCE_ID }};
            struct v2f {{ float4 pos : SV_POSITION; fixed4 color : COLOR; float2 uv : TEXCOORD0; UNITY_VERTEX_OUTPUT_STEREO }};
            v2f vert (appdata v)
            {{
                v2f o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = UnityObjectToClipPos(v.vertex);
                o.color = v.color * _Color;
                o.uv = TRANSFORM_TEX(v.uv, _MainTex);
                return o;
            }}
            fixed4 frag (v2f i) : SV_Target {{ {fragment} }}
            ENDCG
        }}
    }}
}}
");
        AssetDatabase.ImportAsset(path);
        return AssetDatabase.LoadAssetAtPath<Shader>(path);
    }

    public static Material PanelMaterial(Color color)
    {
        string name = $"panel_{ColorUtility.ToHtmlStringRGBA(color)}";
        if (Materials.TryGetValue(name, out var material)) return material;
        material = new Material(PanelShader()) { mainTexture = RoundedPanel(), color = color, renderQueue = 3000 };
        return Save(name, material);
    }

    // White rounded rectangle; the panel colour comes from the material.
    static Texture2D RoundedPanel()
    {
        if (roundedPanel != null) return roundedPanel;
        const int w = 256, h = 128, r = 36;
        var texture = new Texture2D(w, h);
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++)
            {
                float dx = Mathf.Max(0, Mathf.Max(r - x, x - (w - 1 - r)));
                float dy = Mathf.Max(0, Mathf.Max(r - y, y - (h - 1 - r)));
                float alpha = Mathf.Clamp01(r + 0.5f - Mathf.Sqrt(dx * dx + dy * dy));
                texture.SetPixel(x, y, new Color(1f, 1f, 1f, alpha));
            }
        texture.Apply();
        return roundedPanel = SaveTexture("rounded", texture, TextureWrapMode.Clamp);
    }

    public static Mesh InvertedSphere()
    {
        if (invertedSphere != null) return invertedSphere;
        var probe = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        var mesh = Object.Instantiate(probe.GetComponent<MeshFilter>().sharedMesh);
        Object.DestroyImmediate(probe);
        var triangles = mesh.triangles;
        for (int i = 0; i < triangles.Length; i += 3)
            (triangles[i], triangles[i + 1]) = (triangles[i + 1], triangles[i]);
        mesh.triangles = triangles;
        mesh.RecalculateNormals();
        AssetDatabase.CreateAsset(mesh, $"{Generated}/InvertedSphere.asset");
        return invertedSphere = mesh;
    }

    // VRChat copies the reference camera's post-processing onto each player's camera.
    static GameObject ReferenceCamera()
    {
        var holder = new GameObject("ReferenceCamera");
        var camera = holder.AddComponent<Camera>();
        camera.enabled = false;
        camera.farClipPlane = 300f;
        AddPostLayer(holder);
        return holder;
    }

    public static void AddPostLayer(GameObject camera)
    {
        var layer = camera.AddComponent<PostProcessLayer>();
        layer.Init(AssetDatabase.LoadAssetAtPath<PostProcessResources>(PostResources));
        layer.volumeLayer = 1 << PostLayer;
        layer.volumeTrigger = camera.transform;
    }

    // Bloom, colour grading and vignette for one zone, as most worlds add.
    public static void PostVolume(Transform zone, string name, float bloom, float temperature, float saturation, float exposure, float vignette)
    {
        var holder = new GameObject("PostVolume") { layer = PostLayer };
        holder.transform.SetParent(zone, false);
        var box = holder.AddComponent<BoxCollider>();
        box.isTrigger = true;
        box.center = new Vector3(0f, 10f, 0f);
        box.size = new Vector3(Spacing * 0.95f, 40f, Spacing * 0.95f);
        var volume = holder.AddComponent<PostProcessVolume>();
        volume.isGlobal = false;
        var profile = ScriptableObject.CreateInstance<PostProcessProfile>();
        var glow = profile.AddSettings<Bloom>();
        glow.enabled.Override(true);
        glow.intensity.Override(bloom);
        glow.threshold.Override(1f);
        var grading = profile.AddSettings<ColorGrading>();
        grading.enabled.Override(true);
        grading.temperature.Override(temperature);
        grading.saturation.Override(saturation);
        grading.postExposure.Override(exposure);
        var edge = profile.AddSettings<Vignette>();
        edge.enabled.Override(vignette > 0f);
        edge.intensity.Override(vignette);
        AssetDatabase.CreateAsset(profile, $"{Generated}/post_{name}.asset");
        foreach (var setting in profile.settings)
            AssetDatabase.AddObjectToAsset(setting, profile);
        volume.sharedProfile = profile;
    }

    static GameObject BuildDirector(Transform[] zones)
    {
        var holder = new GameObject("ChatboxLabDirector");
        var director = UdonSharpUndo.AddComponent<ChatboxLabDirector>(holder);
        director.zones = zones;
        UdonSharpEditorUtility.CopyProxyToUdon(director);
        return holder;
    }

    // ---- materials --------------------------------------------------------

    static Material Save(string name, Material material)
    {
        AssetDatabase.CreateAsset(material, $"{Generated}/{name}.mat");
        Materials[name] = material;
        return material;
    }

    public static Material Solid(string name, Color color, float glossiness = 0.2f)
    {
        if (Materials.TryGetValue(name, out var material)) return material;
        material = new Material(Shader.Find("Standard")) { color = color };
        material.SetFloat("_Glossiness", glossiness);
        return Save(name, material);
    }

    // scale 0 keeps the plain zones' tiling (4 x 2).
    public static Material Textured(string name, Texture2D texture, float scale = 0f)
    {
        if (Materials.TryGetValue(name, out var material)) return material;
        material = new Material(Shader.Find("Standard")) { mainTexture = SaveTexture(name, texture) };
        material.mainTextureScale = scale > 0f ? new Vector2(scale, scale) : new Vector2(4f, 2f);
        material.SetFloat("_Glossiness", 0.1f);
        return Save(name, material);
    }

    public static Material Emissive(string name, Texture2D texture, Color color, float intensity, float scale = 1f)
    {
        if (Materials.TryGetValue(name, out var material)) return material;
        material = new Material(Shader.Find("Standard")) { color = texture != null ? Color.black : color * 0.3f };
        material.EnableKeyword("_EMISSION");
        material.SetColor("_EmissionColor", color * intensity);
        material.globalIlluminationFlags = MaterialGlobalIlluminationFlags.None;
        if (texture != null)
        {
            var saved = SaveTexture(name, texture);
            material.mainTexture = saved;
            material.SetTexture("_EmissionMap", saved);
            material.mainTextureScale = new Vector2(scale, scale);
        }
        return Save(name, material);
    }

    public static Material Unlit(string name, Texture2D texture)
    {
        if (Materials.TryGetValue(name, out var material)) return material;
        material = new Material(Shader.Find("Unlit/Texture")) { mainTexture = SaveTexture(name, texture, TextureWrapMode.Clamp) };
        return Save(name, material);
    }

    public static Material ParticleMaterial(Color color)
    {
        string name = $"particle_{ColorUtility.ToHtmlStringRGB(color)}";
        if (Materials.TryGetValue(name, out var material)) return material;
        material = new Material(Shader.Find("Particles/Standard Unlit")) { color = color };
        return Save(name, material);
    }

    static Texture2D SaveTexture(string name, Texture2D texture, TextureWrapMode wrap = TextureWrapMode.Repeat)
    {
        string path = $"{Generated}/{name}.png";
        File.WriteAllBytes(path, texture.EncodeToPNG());
        AssetDatabase.ImportAsset(path);
        var importer = (TextureImporter)AssetImporter.GetAtPath(path);
        importer.wrapMode = wrap;
        importer.alphaIsTransparency = true;
        importer.SaveAndReimport();
        return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
    }

    // ---- procedural textures ---------------------------------------------

    static Texture2D Paint(int width, int height, System.Func<int, int, Color> color)
    {
        var texture = new Texture2D(width, height);
        var pixels = new Color[width * height];
        for (int y = 0; y < height; y++)
            for (int x = 0; x < width; x++)
                pixels[y * width + x] = color(x, y);
        texture.SetPixels(pixels);
        texture.Apply();
        return texture;
    }

    static Color Shade(Color color, float amount) => new Color(color.r * amount, color.g * amount, color.b * amount, color.a);

    public static Texture2D Noise(Color color, float amount, System.Random random)
    {
        float ox = random.Next(1000), oy = random.Next(1000);
        return Paint(256, 256, (x, y) =>
            Shade(color, 1f + amount * (Mathf.PerlinNoise(ox + x * 0.05f, oy + y * 0.05f) - 0.5f) * 2f + amount * ((x * 7919 + y * 104729) % 97 / 97f - 0.5f)));
    }

    public static Texture2D Planks(Color color, System.Random random, bool vertical)
    {
        var tones = new float[16];
        for (int i = 0; i < tones.Length; i++) tones[i] = 0.8f + 0.4f * (float)random.NextDouble();
        float ox = random.Next(1000);
        return Paint(256, 256, (x, y) =>
        {
            int across = vertical ? x : y, along = vertical ? y : x;
            int plank = across / 32;
            if (across % 32 == 0) return Shade(color, 0.45f);
            float grain = Mathf.PerlinNoise(ox + along * 0.02f, plank * 3.1f + across * 0.3f);
            return Shade(color, tones[plank % tones.Length] * (0.85f + 0.3f * grain));
        });
    }

    public static Texture2D Tatami(System.Random random)
    {
        var straw = new Color(0.72f, 0.7f, 0.45f);
        return Paint(256, 256, (x, y) =>
        {
            if (x % 128 < 6 || y % 256 < 6) return new Color(0.15f, 0.18f, 0.12f);
            return Shade(straw, 0.9f + 0.15f * ((y / 2) % 2) + 0.05f * Mathf.PerlinNoise(x * 0.3f, y * 0.01f));
        });
    }

    public static Texture2D Shoji() => Paint(256, 256, (x, y) =>
        x % 64 < 5 || y % 64 < 5 ? new Color(0.45f, 0.3f, 0.18f) : new Color(0.97f, 0.95f, 0.88f));

    public static Texture2D Bricks(System.Random random)
    {
        var tones = new float[64];
        for (int i = 0; i < tones.Length; i++) tones[i] = 0.75f + 0.4f * (float)random.NextDouble();
        return Paint(256, 256, (x, y) =>
        {
            int row = y / 32, shifted = x + (row % 2) * 32;
            if (y % 32 < 4 || shifted % 64 < 4) return new Color(0.75f, 0.72f, 0.66f);
            return Shade(new Color(0.62f, 0.3f, 0.22f), tones[(row * 5 + shifted / 64) % tones.Length]);
        });
    }

    public static Texture2D Tiles(Color a, Color b) => Paint(256, 256, (x, y) =>
        x % 64 < 2 || y % 64 < 2 ? Shade(a, 0.6f) : ((x / 64 + y / 64) % 2 == 0 ? a : b));

    public static Texture2D Books(System.Random random)
    {
        var colors = new Color[24];
        var widths = new int[24];
        for (int i = 0; i < colors.Length; i++)
        {
            colors[i] = Color.HSVToRGB((float)random.NextDouble(), 0.4f + 0.5f * (float)random.NextDouble(), 0.3f + 0.6f * (float)random.NextDouble());
            widths[i] = 6 + random.Next(10);
        }
        return Paint(512, 256, (x, y) =>
        {
            if (y % 64 < 6) return new Color(0.35f, 0.24f, 0.15f);
            int i = 0, edge = widths[0] + (y / 64) * 7;
            while (x % 256 > edge) { i++; edge += widths[i % widths.Length]; }
            int top = 64 - 8 - (i * 7) % 18;
            return y % 64 > top ? new Color(0.2f, 0.15f, 0.1f) : colors[(i + y / 64 * 5) % colors.Length];
        });
    }

    public static Texture2D Windows(System.Random random)
    {
        var lit = new bool[32 * 32];
        for (int i = 0; i < lit.Length; i++) lit[i] = random.Next(3) > 0;
        return Paint(256, 256, (x, y) =>
        {
            int cx = x / 8, cy = y / 8;
            bool window = x % 8 > 1 && x % 8 < 7 && y % 8 > 2;
            if (!window) return new Color(0.05f, 0.05f, 0.07f);
            return lit[cy * 32 + cx] ? new Color(1f, 0.85f, 0.55f) : new Color(0.08f, 0.1f, 0.14f);
        });
    }

    public static Texture2D Gradient(Color top, Color horizon, Color bottom, bool stars, System.Random random)
    {
        var sky = Paint(512, 256, (x, y) =>
        {
            float v = y / 255f;
            return v >= 0.5f ? Color.Lerp(horizon, top, Mathf.Pow((v - 0.5f) * 2f, 0.6f)) : Color.Lerp(horizon, bottom, Mathf.Pow((0.5f - v) * 2f, 0.4f));
        });
        if (stars)
        {
            for (int i = 0; i < 600; i++)
                sky.SetPixel(random.Next(512), 140 + random.Next(116), Color.white * (0.5f + 0.5f * (float)random.NextDouble()));
            sky.Apply();
        }
        return sky;
    }

    public static Texture2D VideoFrame(System.Random random)
    {
        float hue = (float)random.NextDouble();
        return Paint(320, 180, (x, y) =>
        {
            float wave = Mathf.Sin(x * 0.04f + y * 0.03f) * 0.5f + 0.5f;
            var color = Color.HSVToRGB((hue + 0.3f * x / 320f) % 1f, 0.6f, 0.4f + 0.6f * wave);
            float dx = x - 210, dy = y - 100;
            return dx * dx + dy * dy < 1600 ? new Color(1f, 0.95f, 0.8f) : color;
        });
    }

    public static Texture2D Thumbnail(System.Random random)
    {
        var back = Color.HSVToRGB((float)random.NextDouble(), 0.4f, 0.9f);
        var hair = Color.HSVToRGB((float)random.NextDouble(), 0.6f, 0.8f);
        return Paint(128, 96, (x, y) =>
        {
            float dx = x - 64, dy = y - 44;
            if (dx * dx + dy * dy < 700) return new Color(1f, 0.88f, 0.8f);
            if (dx * dx + (dy - 12) * (dy - 12) < 1100 && y > 40) return hair;
            return back;
        });
    }

    static Texture2D Stripes()
    {
        var colors = new[] { new Color(0.9f, 0.3f, 0.3f), new Color(0.95f, 0.9f, 0.3f), new Color(0.3f, 0.5f, 0.9f), new Color(0.95f, 0.95f, 0.95f) };
        return Paint(256, 256, (x, y) => colors[((x + y) / 32) % colors.Length]);
    }

    static Texture2D Clutter(System.Random random)
    {
        var texture = new Texture2D(512, 512);
        var pixels = new Color[512 * 512];
        for (int i = 0; i < pixels.Length; i++) pixels[i] = new Color(0.5f, 0.5f, 0.5f);
        for (int n = 0; n < 120; n++)
        {
            int cx = random.Next(512), cy = random.Next(512), w = random.Next(8, 90), h = random.Next(8, 90);
            var color = new Color((float)random.NextDouble(), (float)random.NextDouble(), (float)random.NextDouble());
            for (int y = cy; y < Mathf.Min(512, cy + h); y++)
                for (int x = cx; x < Mathf.Min(512, cx + w); x++)
                    pixels[y * 512 + x] = color;
        }
        texture.SetPixels(pixels);
        texture.Apply();
        return texture;
    }
}
