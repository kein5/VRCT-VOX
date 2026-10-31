using System.IO;
using UdonSharp;
using UdonSharpEditor;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

// Builds the chatbox photo world from code, so it can be rebuilt and reviewed.
// Each zone gives the chatbox a different background and light: dark and
// bright rooms, open sky, busy textures, coloured neon, and signs with text as
// hard negatives. No third-party assets are used.
public static class ChatboxLabSceneBuilder
{
    public const string Root = "Assets/ChatboxLab";
    public const string ScenePath = Root + "/ChatboxLab.unity";
    const string Generated = Root + "/Generated";
    const string WorldPrefab = "Packages/com.vrchat.worlds/Samples/UdonExampleScene/Prefabs/VRCWorld.prefab";
    const float Spacing = 60f;
    const float RoomSize = 24f;
    const float WallHeight = 8f;

    static readonly string[] SignWords =
    {
        "OPEN", "WELCOME", "EXIT", "STAGE", "CAFE", "MUSIC", "EVENT 21:00", "NO SMOKING", "LOBBY",
        "VRChat", "Hello World", "1F", "B2", "SALE 50%", "Mirror", "Quest OK", "PC ONLY", "DJ BOOTH",
    };

    const string ScriptPath = Root + "/ChatboxLabDirector.cs";
    const string ProgramPath = Root + "/ChatboxLabDirector.asset";

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
        Directory.CreateDirectory(Generated);
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        RenderSettings.ambientMode = AmbientMode.Trilight;
        RenderSettings.ambientSkyColor = new Color(0.55f, 0.6f, 0.7f);
        RenderSettings.ambientEquatorColor = new Color(0.4f, 0.4f, 0.4f);
        RenderSettings.ambientGroundColor = new Color(0.2f, 0.2f, 0.2f);

        var sun = new GameObject("Sun").AddComponent<Light>();
        sun.type = LightType.Directional;
        sun.intensity = 1.0f;
        sun.transform.rotation = Quaternion.Euler(50f, -30f, 0f);

        var random = new System.Random(20261101);
        var zones = new Transform[8];
        for (int i = 0; i < zones.Length; i++)
            zones[i] = BuildZone(i, random);

        var world = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(WorldPrefab));
        world.transform.position = zones[0].position;

        var director = BuildDirector(zones);
        EditorSceneManager.SaveScene(scene, ScenePath);
        EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
        AssetDatabase.SaveAssets();
        Debug.Log($"Chatbox lab scene built with {zones.Length} zones and director {director.name}");
    }

    static Transform BuildZone(int index, System.Random random)
    {
        var zone = new GameObject($"Zone{index}").transform;
        zone.position = new Vector3(index * Spacing, 0f, 0f);
        var floor = Box(zone, "Floor", new Vector3(0f, -0.25f, 0f), new Vector3(RoomSize + 6f, 0.5f, RoomSize + 6f),
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
            var position = zone.position + rotation * Vector3.forward * (RoomSize / 2f - 0.4f) + Vector3.up * (1.5f + (float)random.NextDouble() * 3f);
            Sign(zone, SignWords[random.Next(SignWords.Length)], position, rotation, random);
        }
        return zone;
    }

    static GameObject Box(Transform parent, string name, Vector3 local, Vector3 size, Material material)
    {
        var box = GameObject.CreatePrimitive(PrimitiveType.Cube);
        box.name = name;
        box.transform.SetParent(parent, false);
        box.transform.localPosition = local;
        box.transform.localScale = size;
        box.GetComponent<Renderer>().sharedMaterial = material;
        return box;
    }

    static void Lamp(Transform zone, Color color, float intensity, Vector3? local = null)
    {
        var lamp = new GameObject("Lamp").AddComponent<Light>();
        lamp.transform.SetParent(zone, false);
        lamp.transform.localPosition = local ?? new Vector3(0f, 6f, 0f);
        lamp.type = LightType.Point;
        lamp.range = 25f;
        lamp.color = color;
        lamp.intensity = intensity;
    }

    static void Sign(Transform zone, string text, Vector3 position, Quaternion rotation, System.Random random)
    {
        var board = GameObject.CreatePrimitive(PrimitiveType.Quad);
        board.name = "Sign";
        board.transform.SetParent(zone, true);
        board.transform.position = position;
        board.transform.rotation = rotation;
        board.transform.localScale = new Vector3(0.35f * text.Length + 0.6f, 0.9f, 1f);
        Object.DestroyImmediate(board.GetComponent<Collider>());
        bool light = random.Next(2) == 0;
        board.GetComponent<Renderer>().sharedMaterial = Solid(light ? "sign_light" : "sign_dark", light ? new Color(0.9f, 0.88f, 0.8f) : new Color(0.1f, 0.1f, 0.15f));
        var label = new GameObject("Text").AddComponent<TextMesh>();
        label.transform.SetParent(board.transform, false);
        label.transform.localPosition = new Vector3(0f, 0f, -0.01f);
        label.transform.localScale = new Vector3(1f / board.transform.localScale.x, 1f / board.transform.localScale.y, 1f) * 0.12f;
        label.text = text;
        label.anchor = TextAnchor.MiddleCenter;
        label.fontSize = 48;
        label.color = light ? new Color(0.1f, 0.1f, 0.1f) : new Color(0.95f, 0.95f, 0.9f);
        label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        label.GetComponent<MeshRenderer>().sharedMaterial = label.font.material;
    }

    static GameObject BuildDirector(Transform[] zones)
    {
        var holder = new GameObject("ChatboxLabDirector");
        var director = UdonSharpUndo.AddComponent<ChatboxLabDirector>(holder);
        director.zones = zones;
        UdonSharpEditorUtility.CopyProxyToUdon(director);
        return holder;
    }

    static Material Solid(string name, Color color)
    {
        string path = $"{Generated}/{name}.mat";
        var material = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (material != null) return material;
        material = new Material(Shader.Find("Standard")) { color = color };
        material.SetFloat("_Glossiness", 0.2f);
        AssetDatabase.CreateAsset(material, path);
        return material;
    }

    static Material Textured(string name, Texture2D texture)
    {
        string texturePath = $"{Generated}/{name}.png";
        File.WriteAllBytes(texturePath, texture.EncodeToPNG());
        AssetDatabase.ImportAsset(texturePath);
        var material = new Material(Shader.Find("Standard"));
        material.mainTexture = AssetDatabase.LoadAssetAtPath<Texture2D>(texturePath);
        material.mainTextureScale = new Vector2(4f, 2f);
        material.SetFloat("_Glossiness", 0.1f);
        AssetDatabase.CreateAsset(material, $"{Generated}/{name}.mat");
        return material;
    }

    static Texture2D Stripes()
    {
        var texture = new Texture2D(256, 256);
        var colors = new[] { new Color(0.9f, 0.3f, 0.3f), new Color(0.95f, 0.9f, 0.3f), new Color(0.3f, 0.5f, 0.9f), new Color(0.95f, 0.95f, 0.95f) };
        for (int y = 0; y < 256; y++)
            for (int x = 0; x < 256; x++)
                texture.SetPixel(x, y, colors[((x + y) / 32) % colors.Length]);
        texture.Apply();
        return texture;
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
